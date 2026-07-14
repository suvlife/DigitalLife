import asyncio
import random
import time
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
import json
import logging
import uuid
from typing import Optional, TYPE_CHECKING

from constants import InferRequestStateType, LlmErrorCategory, LlmServiceType

logger = logging.getLogger(__name__)

# 请求门按 LLM 服务隔离，避免慢服务占满全局并发。生命周期内配置变化时自动重建。
_SERVICE_REQUEST_GATES: dict[str, "ServiceRequestGate"] = {}
from model.coreModel.gtCoreChatModel import GtCoreAgentDialogContext
from service.llmService.llmErrorClassifier import classify_llm_error, RETRYABLE_CATEGORIES
from service.llmService.llmRequestRules import apply_llm_request_rules
from util import configUtil, llmApiUtil

if TYPE_CHECKING:
    from util.configTypes import LlmServiceConfig

# LiteLLM custom_llm_provider 映射表
_TYPE_TO_PROVIDER = {
    LlmServiceType.OPENAI_COMPATIBLE: "openai",
    LlmServiceType.ANTHROPIC: "anthropic",
    LlmServiceType.GOOGLE: "gemini",
    LlmServiceType.DEEPSEEK: "deepseek",
}

logger = logging.getLogger(__name__)

_INFER_RETRY_DELAYS_SECONDS = (3, 5, 10, 15, 30, 30, 60, 60)  # 默认退避
_RATE_LIMIT_RETRY_DELAYS = (10, 20, 30, 60, 60, 60, 90, 90)  # RateLimitError 专用退避（更长）


@dataclass
class InferPerformanceMetrics:
    """单次推理（含重试）的关键性能指标，单位均为毫秒。"""

    queue_wait_ms: int = 0
    rate_limit_wait_ms: int = 0
    infer_duration_ms: int = 0
    retry_wait_ms: int = 0
    attempts: int = 0


class SlidingWindowRateLimiter:
    """进程内、按服务隔离的请求级 RPM 滑动窗口。

    这是主动保护而非分布式配额协调。多进程部署仍应使用网关/Redis 做全局限流。
    """

    def __init__(self, requests_per_minute: int) -> None:
        self.requests_per_minute = max(0, requests_per_minute)
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> float:
        if self.requests_per_minute <= 0:
            return 0.0
        waited = 0.0
        while True:
            async with self._lock:
                now = time.monotonic()
                cutoff = now - 60.0
                while self._timestamps and self._timestamps[0] <= cutoff:
                    self._timestamps.popleft()
                if len(self._timestamps) < self.requests_per_minute:
                    self._timestamps.append(now)
                    return waited
                delay = max(0.001, 60.0 - (now - self._timestamps[0]))
            started = time.monotonic()
            await asyncio.sleep(delay)
            waited += time.monotonic() - started


class ServiceRequestGate:
    """一个 LLM 服务的独立并发池和 RPM 限流器。"""

    def __init__(self, max_concurrency: int, requests_per_minute: int) -> None:
        self.max_concurrency = max_concurrency
        self.requests_per_minute = requests_per_minute
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._rate_limiter = SlidingWindowRateLimiter(requests_per_minute)

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[tuple[float, float]]:
        queue_started = time.monotonic()
        rate_wait_seconds = await self._rate_limiter.acquire()
        await self._semaphore.acquire()
        queue_wait_seconds = time.monotonic() - queue_started
        try:
            yield queue_wait_seconds, rate_wait_seconds
        finally:
            self._semaphore.release()


def _service_gate_key(llm_config: "LlmServiceConfig") -> str:
    return f"{llm_config.name}|{llm_config.base_url}"


def _get_service_request_gate(llm_config: "LlmServiceConfig") -> ServiceRequestGate:
    key = _service_gate_key(llm_config)
    max_concurrency = int(getattr(llm_config, "max_concurrency", 5) or 5)
    requests_per_minute = int(getattr(llm_config, "requests_per_minute", 0) or 0)
    gate = _SERVICE_REQUEST_GATES.get(key)
    if gate is None or (gate.max_concurrency, gate.requests_per_minute) != (max_concurrency, requests_per_minute):
        gate = ServiceRequestGate(max_concurrency, requests_per_minute)
        _SERVICE_REQUEST_GATES[key] = gate
    return gate


def reset_request_gates_for_testing() -> None:
    """清空进程内请求门；配置热更新和测试隔离可调用。"""
    _SERVICE_REQUEST_GATES.clear()


@dataclass
class InferResult:
    ok: bool
    response: Optional[llmApiUtil.OpenAIResponse] = None
    error_message: str = ""
    error: Optional[Exception] = None
    error_category: Optional[LlmErrorCategory] = None
    request_id: str = ""
    performance: InferPerformanceMetrics = field(default_factory=InferPerformanceMetrics)

    @classmethod
    def success(
        cls,
        response: llmApiUtil.OpenAIResponse,
        request_id: str = "",
        performance: InferPerformanceMetrics | None = None,
    ) -> "InferResult":
        return cls(ok=True, response=response, request_id=request_id, performance=performance or InferPerformanceMetrics())

    @classmethod
    def failure(
        cls,
        error: Exception,
        request_id: str = "",
        performance: InferPerformanceMetrics | None = None,
    ) -> "InferResult":
        return cls(
            ok=False,
            error_message=str(error),
            error=error,
            error_category=classify_llm_error(error),
            request_id=request_id,
            performance=performance or InferPerformanceMetrics(),
        )

    @property
    def usage(self) -> llmApiUtil.OpenAIUsage | None:
        if self.response is None:
            return None
        return self.response.usage


@dataclass
class InferRequestStatusEvent:
    state: InferRequestStateType
    request_id: str = ""
    attempt: int = 0
    max_attempts: int = 0
    retry_delay_seconds: int | None = None
    error_message: str | None = None
    queue_wait_ms: int | None = None
    rate_limit_wait_ms: int | None = None
    infer_duration_ms: int | None = None
    retry_wait_ms: int | None = None


InferRequestStatusEventHandler = Callable[[InferRequestStatusEvent], Awaitable[None]]


async def startup() -> None:
    setting = configUtil.get_app_config().setting
    if not setting.is_llm_configured:
        logger.warning("当前未配置可用的 LLM 服务，Agent 推理功能不可用。请通过 Web Console 或手动编辑 setting.json 完成配置。")


def get_default_model_or_none() -> str | None:
    setting = configUtil.get_app_config().setting
    llm_config = setting.current_llm_service
    if llm_config is None:
        # 回退到内置默认服务
        llm_config = _get_builtin_llm_service()
    if llm_config is None:
        return None
    return llm_config.model


def get_default_model() -> str:
    model = get_default_model_or_none()
    if model is None:
        raise ValueError("未配置可用的 LLM 服务（llm_services 全部被禁用或为空）")
    return model


def get_llm_service_for_team(team_config: dict | None) -> "LlmServiceConfig | None":
    """获取团队级 LLM 服务配置。

    优先级：team_config.llm_service_name → 用户配置的 current_llm_service → 内置默认服务。
    """
    setting = configUtil.get_app_config().setting
    if team_config and isinstance(team_config, dict):
        service_name = team_config.get("llm_service_name")
        if service_name:
            for svc in setting.llm_services:
                if svc.enable and svc.name == service_name:
                    return svc
    # 用户配置的服务
    user_service = setting.current_llm_service
    if user_service is not None:
        return user_service
    # 回退到内置默认服务
    return _get_builtin_llm_service()


# 多 key 轮询：按服务名记录轮询游标，每次调用推进一位，实现多 key 负载均衡。
_API_KEY_ROTATION: dict[str, int] = {}


def _pick_api_key(llm_config: "LlmServiceConfig") -> str:
    """选择本次调用使用的 API Key。

    配置了 api_keys（多个）时按轮询方式选一个，分散请求到不同 key；
    否则回退到单 api_key。空 key 由上层调用报错，此处不做拦截。
    """
    keys = list(llm_config.api_keys or [])
    if len(keys) == 0:
        return llm_config.api_key
    if len(keys) == 1:
        return keys[0]
    idx = _API_KEY_ROTATION.get(llm_config.name, 0) % len(keys)
    _API_KEY_ROTATION[llm_config.name] = (idx + 1) % len(keys)
    return keys[idx]


def _get_builtin_llm_service() -> "LlmServiceConfig | None":
    """获取内置默认 LLM 服务（用户未配置时使用）。"""
    from util.configTypes import LlmServiceConfig, LlmServiceType
    builtin_services = configUtil.get_builtin_llm_services()
    builtin_default = configUtil.get_builtin_default_llm_server()
    for svc in builtin_services:
        if svc.get("enable") and (builtin_default is None or svc.get("name") == builtin_default):
            return LlmServiceConfig(
                name=svc.get("name", "builtin"),
                enable=True,
                base_url=svc.get("base_url", ""),
                api_key=svc.get("api_key", ""),
                api_keys=list(svc.get("api_keys", []) or []),
                type=LlmServiceType(svc.get("type", "openai-compatible")),
                model=svc.get("model", ""),
                context_window_tokens=svc.get("context_window_tokens", 131072),
                reserve_output_tokens=svc.get("reserve_output_tokens", 16384),
                compact_trigger_ratio=svc.get("compact_trigger_ratio", 0.85),
                max_concurrency=svc.get("max_concurrency", 5),
                requests_per_minute=svc.get("requests_per_minute", 0),
            )
    # 如果默认服务未启用，取第一个启用的
    for svc in builtin_services:
        if svc.get("enable"):
            return LlmServiceConfig(
                name=svc.get("name", "builtin"),
                enable=True,
                base_url=svc.get("base_url", ""),
                api_key=svc.get("api_key", ""),
                api_keys=list(svc.get("api_keys", []) or []),
                type=LlmServiceType(svc.get("type", "openai-compatible")),
                model=svc.get("model", ""),
                context_window_tokens=svc.get("context_window_tokens", 131072),
                reserve_output_tokens=svc.get("reserve_output_tokens", 16384),
                compact_trigger_ratio=svc.get("compact_trigger_ratio", 0.85),
                max_concurrency=svc.get("max_concurrency", 5),
                requests_per_minute=svc.get("requests_per_minute", 0),
            )
    return None


def _usage_to_log_json(usage: llmApiUtil.OpenAIUsage | None) -> str:
    if usage is None:
        return "null"
    return json.dumps(usage.model_dump(mode="json", exclude_none=False), ensure_ascii=False, default=str)


def _resolve_primary_llm_service(team_config: dict | None) -> "LlmServiceConfig | None":
    """解析首选 LLM 服务：优先团队级配置，其次用户 current_llm_service，最后内置默认。"""
    if team_config:
        return get_llm_service_for_team(team_config)
    setting = configUtil.get_app_config().setting
    return setting.current_llm_service or _get_builtin_llm_service()


def _resolve_llm_service_chain(team_config: dict | None) -> list["LlmServiceConfig"]:
    """构建 LLM 调用候选链：首选服务在前，随后按 fallback_llm_servers 顺序追加兜底服务。

    审计 #3（LLM 首选 + 兜底 failover）：当首选服务不可用（网络错误/超时/5xx/限流等
    可重试类错误）时，上层按此链顺序切换到下一个兜底服务重试。

    仅收录 enable 的兜底服务；按 name 去重（避免重复调用同一服务）；未找到的名字跳过。
    首选为空时返回空列表。
    """
    primary = _resolve_primary_llm_service(team_config)
    chain: list["LlmServiceConfig"] = []
    seen: set[str] = set()
    if primary is not None:
        chain.append(primary)
        seen.add(primary.name)
    setting = configUtil.get_app_config().setting
    enabled_by_name = {s.name: s for s in setting.llm_services if s.enable}
    for name in setting.fallback_llm_servers:
        if not name or name in seen:
            continue
        svc = enabled_by_name.get(name)
        if svc is None:
            continue
        chain.append(svc)
        seen.add(name)
    return chain


def _build_request(
    *,
    model: str,
    ctx: GtCoreAgentDialogContext,
    llm_config: "LlmServiceConfig",
) -> tuple[llmApiUtil.OpenAIRequest, tuple[str, ...]]:
    messages: list[llmApiUtil.OpenAIMessage] = [
        llmApiUtil.OpenAIMessage.text(llmApiUtil.OpenaiApiRole.SYSTEM, ctx.system_prompt),
        *ctx.messages,
    ]
    request = llmApiUtil.OpenAIRequest(
        model=model,
        messages=messages,
        tools=ctx.tools,
        tool_choice=ctx.tool_choice,
        prompt_cache=ctx.prompt_cache,
        max_tokens=llm_config.reserve_output_tokens,
        temperature=llm_config.temperature,
        provider_params=llm_config.provider_params,
    )
    return apply_llm_request_rules(request)


async def _safe_call_handler(
    on_status_event: InferRequestStatusEventHandler | None,
    event: InferRequestStatusEvent,
) -> None:
    if on_status_event is None:
        return
    try:
        await on_status_event(event)
    except Exception:
        logger.exception(f"LLM request status event callback failed: {event.request_id=}, {event.state.name=}")


async def _send_with_retry(
    send_request: Callable[..., Awaitable[llmApiUtil.OpenAIResponse]],
    args: tuple,
    kwargs: dict,
    *,
    request_gate: ServiceRequestGate,
    metrics: InferPerformanceMetrics,
    on_status_event: InferRequestStatusEventHandler | None = None,
    on_retry_reset: Callable[[], None] | None = None,
    should_block_retry: Callable[[], bool] | None = None,
) -> llmApiUtil.OpenAIResponse:
    last_error: Exception | None = None
    total_attempts = len(_INFER_RETRY_DELAYS_SECONDS) + 1
    request_id = kwargs.get("request_id", "")
    request_name = getattr(send_request, "__name__", repr(send_request))

    for attempt in range(1, total_attempts + 1):
        metrics.attempts = attempt
        try:
            async with request_gate.slot() as (queue_wait_seconds, rate_wait_seconds):
                metrics.queue_wait_ms += round(queue_wait_seconds * 1000)
                metrics.rate_limit_wait_ms += round(rate_wait_seconds * 1000)
                infer_started = time.monotonic()
                try:
                    return await send_request(*args, **kwargs)
                finally:
                    metrics.infer_duration_ms += round((time.monotonic() - infer_started) * 1000)

        except Exception as e:
            last_error = e
            error_category = classify_llm_error(e)
            if error_category not in RETRYABLE_CATEGORIES or attempt >= total_attempts:
                raise

            # M10：流式已产出增量后不整体重试。已 yield / 落库的文本无法回撤，
            # 整体重试会导致下游看到重复内容；此时直接抛出交由上层 failover 处理。
            if should_block_retry is not None and should_block_retry():
                logger.warning(
                    "LLM 已产出输出增量，跳过整体重试以避免重复: request_id=%s, attempt=%s, error=%r",
                    request_id, attempt, e,
                )
                raise

            if error_category == LlmErrorCategory.RATE_LIMITED:
                delay = _RATE_LIMIT_RETRY_DELAYS[min(attempt - 1, len(_RATE_LIMIT_RETRY_DELAYS) - 1)]
                logger.warning("LLM RateLimit 退避: request_id=%s, attempt=%s, delay=%ss", request_id, attempt, delay)
            else:
                delay = _INFER_RETRY_DELAYS_SECONDS[attempt - 1]

            if on_retry_reset is not None:
                on_retry_reset()
            await _safe_call_handler(
                on_status_event,
                InferRequestStatusEvent(
                    state=InferRequestStateType.RETRY_SCHEDULED,
                    request_id=request_id,
                    attempt=attempt,
                    max_attempts=total_attempts,
                    retry_delay_seconds=delay,
                    error_message=str(e),
                    queue_wait_ms=metrics.queue_wait_ms,
                    rate_limit_wait_ms=metrics.rate_limit_wait_ms,
                    infer_duration_ms=metrics.infer_duration_ms,
                    retry_wait_ms=metrics.retry_wait_ms,
                ),
            )
            logger.warning("LLM infer retry scheduled: request_id=%s, request_name=%s, attempt=%s/%s, delay=%s, error=%r", request_id, request_name, attempt, total_attempts, delay, e)
            jittered_delay = delay + random.uniform(0, delay * 0.1)
            retry_wait_started = time.monotonic()
            await asyncio.sleep(jittered_delay)
            metrics.retry_wait_ms += round((time.monotonic() - retry_wait_started) * 1000)
            await _safe_call_handler(
                on_status_event,
                InferRequestStatusEvent(
                    state=InferRequestStateType.RETRYING,
                    request_id=request_id,
                    attempt=attempt + 1,
                    max_attempts=total_attempts,
                    queue_wait_ms=metrics.queue_wait_ms,
                    rate_limit_wait_ms=metrics.rate_limit_wait_ms,
                    infer_duration_ms=metrics.infer_duration_ms,
                    retry_wait_ms=metrics.retry_wait_ms,
                ),
            )

    assert last_error is not None
    raise last_error


async def infer(
    model: str | None,
    ctx: GtCoreAgentDialogContext,
    on_status_event: InferRequestStatusEventHandler | None = None,
    team_config: dict | None = None,
) -> InferResult:
    """根据 GtCoreAgentDialogContext 组装请求并调用 LLM 推理接口，统一返回成功/失败结果。

    Args:
        team_config: 团队级配置 dict（含 llm_service_name）。传入时优先使用团队级 LLM 服务。
    """
    request_id = uuid.uuid4().hex
    resolved_model = model
    resolved_provider: str | None = None
    metrics = InferPerformanceMetrics()
    try:
        candidates = _resolve_llm_service_chain(team_config)
        if not candidates:
            raise ValueError("未配置可用的 LLM 服务（llm_services 全部被禁用或为空）")
        last_error: Exception | None = None
        for idx, llm_config in enumerate(candidates):
            is_last = idx == len(candidates) - 1
            resolved_model = model or llm_config.model
            resolved_provider = _TYPE_TO_PROVIDER.get(llm_config.type)
            request, applied_rules = _build_request(
                model=resolved_model,
                ctx=ctx,
                llm_config=llm_config,
            )
            logger.info(
                "LLM infer start: request_id=%s, stream=%s, service=%s, failover_index=%d/%d, model=%s, provider=%s, message_count=%d, tool_count=%d, tool_choice=%s, prompt_cache=%s, applied_rules=%s",
                request_id, False, llm_config.name, idx, len(candidates) - 1, resolved_model, resolved_provider, len(request.messages), len(ctx.tools or []), request.tool_choice,
                ctx.prompt_cache, list(applied_rules),
            )
            request_gate = _get_service_request_gate(llm_config)
            try:
                response = await _send_with_retry(
                    send_request=llmApiUtil.send_request_non_stream,
                    args=(),
                    kwargs={
                        "request": request,
                        "url": llm_config.base_url,
                        "api_key": _pick_api_key(llm_config),
                        "custom_llm_provider": resolved_provider,
                        "extra_headers": llm_config.extra_headers,
                        "request_id": request_id,
                    },
                    request_gate=request_gate,
                    metrics=metrics,
                    on_status_event=on_status_event,
                )
            except Exception as e:
                last_error = e
                category = classify_llm_error(e)
                # #3 failover：可重试/不可用类错误且仍有兜底服务时，切换到下一个服务；
                # 永久错误（鉴权/400/上下文超长/内容策略）不切换，直接抛出。
                if not is_last and category in RETRYABLE_CATEGORIES:
                    logger.warning(
                        "LLM failover: service=%s 调用失败(category=%s)，切换到下一个兜底服务: request_id=%s, error=%r",
                        llm_config.name, category.name, request_id, e,
                    )
                    continue
                raise
            logger.info(
                "LLM infer success: request_id=%s, stream=%s, service=%s, upstream_request_id=%s, usage=%s, queue_wait_ms=%s, rate_limit_wait_ms=%s, infer_duration_ms=%s, retry_wait_ms=%s, attempts=%s",
                request_id, False, llm_config.name, response.request_id, _usage_to_log_json(response.usage),
                metrics.queue_wait_ms, metrics.rate_limit_wait_ms, metrics.infer_duration_ms, metrics.retry_wait_ms, metrics.attempts,
            )
            return InferResult.success(response, request_id=request_id, performance=metrics)
        assert last_error is not None  # 循环内要么 return 要么 raise，不会正常退出
        raise last_error
    except Exception as e:
        logger.exception(
            "LLM infer failed: request_id=%s, stream=%s, model=%s, provider=%s",
            request_id, False, resolved_model, resolved_provider,
        )
        return InferResult.failure(e, request_id=request_id, performance=metrics)


def shutdown() -> None:
    reset_request_gates_for_testing()


@dataclass
class InferStreamProgress:
    """流式推理进度回调数据。"""
    delta_text: str
    current_completion_tokens: int | None = None
    current_total_tokens: int | None = None

    def to_metadata_patch(self) -> dict:
        """返回适合 metadata 浅合并的字典（排除 delta_text 和 None 值）。"""
        return {k: v for k, v in asdict(self).items() if k != "delta_text" and v is not None}


async def infer_stream(
    model: str | None,
    ctx: GtCoreAgentDialogContext,
    on_progress: Callable[[InferStreamProgress], Awaitable[None] | None] | None = None,
    on_status_event: InferRequestStatusEventHandler | None = None,
    team_config: dict | None = None,
) -> InferResult:
    """流式推理：边迭代 chunk 边回调 on_progress，完成后返回与 infer() 一致的 InferResult。

    Args:
        team_config: 团队级配置 dict（含 llm_service_name）。传入时优先使用团队级 LLM 服务。
    """
    request_id = uuid.uuid4().hex
    resolved_model = model
    resolved_provider: str | None = None
    metrics = InferPerformanceMetrics()
    try:
        candidates = _resolve_llm_service_chain(team_config)
        if not candidates:
            raise ValueError("未配置可用的 LLM 服务（llm_services 全部被禁用或为空）")

        # 用可变容器持有流式状态，以便 _send_with_retry 回调重置 / 读取。
        # produced_output：一旦向下游 yield 过增量即为 True，M10 据此禁止整体重试与 failover
        # （已推送/落库文本无法回撤，重来会导致下游看到重复内容）。
        stream_state = {"completion_tokens": 0, "produced_output": False}

        async def _on_chunk(chunk: llmApiUtil.ModelResponseStream) -> None:
            if on_progress is None:
                return

            delta_text = ""
            choices = getattr(chunk, "choices", None)
            if choices and len(choices) > 0:
                delta = getattr(choices[0], "delta", None)
                if delta:
                    delta_text = getattr(delta, "content", None) or ""

            chunk_usage = getattr(chunk, "usage", None)
            if chunk_usage and getattr(chunk_usage, "completion_tokens", None) is not None:
                current_ct = chunk_usage.completion_tokens
                current_total = getattr(chunk_usage, "total_tokens", None)
            else:
                if delta_text:
                    stream_state["completion_tokens"] += 1
                current_ct = stream_state["completion_tokens"]
                current_total = None

            if delta_text:
                stream_state["produced_output"] = True

            progress = InferStreamProgress(
                delta_text=delta_text,
                current_completion_tokens=current_ct,
                current_total_tokens=current_total,
            )
            result = on_progress(progress)
            if result is not None:
                import inspect
                if inspect.isawaitable(result):
                    await result

        last_error: Exception | None = None
        for idx, llm_config in enumerate(candidates):
            is_last = idx == len(candidates) - 1
            resolved_model = model or llm_config.model
            resolved_provider = _TYPE_TO_PROVIDER.get(llm_config.type)
            request, applied_rules = _build_request(
                model=resolved_model,
                ctx=ctx,
                llm_config=llm_config,
            )
            logger.info(
                "LLM infer start: request_id=%s, stream=%s, service=%s, failover_index=%d/%d, model=%s, provider=%s, message_count=%d, tool_count=%d, tool_choice=%s, prompt_cache=%s, applied_rules=%s",
                request_id, True, llm_config.name, idx, len(candidates) - 1, resolved_model, resolved_provider, len(request.messages), len(ctx.tools or []), request.tool_choice,
                ctx.prompt_cache, list(applied_rules),
            )

            # 每个候选服务重试前重置 completion_tokens 计数。
            stream_state["completion_tokens"] = 0
            request_gate = _get_service_request_gate(llm_config)
            try:
                response = await _send_with_retry(
                    send_request=llmApiUtil.send_request_stream,
                    args=(),
                    kwargs={
                        "request": request,
                        "url": llm_config.base_url,
                        "api_key": _pick_api_key(llm_config),
                        "custom_llm_provider": resolved_provider,
                        "extra_headers": llm_config.extra_headers,
                        "on_chunk": _on_chunk,
                        "request_id": request_id,
                    },
                    request_gate=request_gate,
                    metrics=metrics,
                    on_status_event=on_status_event,
                    on_retry_reset=lambda: stream_state.update(completion_tokens=0),
                    should_block_retry=lambda: stream_state["produced_output"],
                )
            except Exception as e:
                last_error = e
                category = classify_llm_error(e)
                # #3 failover：可重试/不可用类错误且仍有兜底服务时切换下一个服务。
                # M10：一旦已产出输出增量则不再 failover，避免下游重复内容。
                if not is_last and category in RETRYABLE_CATEGORIES and not stream_state["produced_output"]:
                    logger.warning(
                        "LLM failover: service=%s 流式调用失败(category=%s)，切换到下一个兜底服务: request_id=%s, error=%r",
                        llm_config.name, category.name, request_id, e,
                    )
                    continue
                raise
            logger.info(
                "LLM infer success: request_id=%s, stream=%s, service=%s, upstream_request_id=%s, usage=%s, queue_wait_ms=%s, rate_limit_wait_ms=%s, infer_duration_ms=%s, retry_wait_ms=%s, attempts=%s",
                request_id, True, llm_config.name, response.request_id, _usage_to_log_json(response.usage),
                metrics.queue_wait_ms, metrics.rate_limit_wait_ms, metrics.infer_duration_ms, metrics.retry_wait_ms, metrics.attempts,
            )
            return InferResult.success(response, request_id=request_id, performance=metrics)
        assert last_error is not None  # 循环内要么 return 要么 raise，不会正常退出
        raise last_error
    except Exception as e:
        logger.exception(
            "LLM infer failed: request_id=%s, stream=%s, model=%s, provider=%s",
            request_id, True, resolved_model, resolved_provider,
        )
        return InferResult.failure(e, request_id=request_id, performance=metrics)
