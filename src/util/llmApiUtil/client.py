import json
import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import litellm
from litellm.litellm_core_utils.streaming_handler import CustomStreamWrapper
from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler
from litellm.types.utils import ModelResponse, ModelResponseStream, TextCompletionResponse
from constants import OpenaiApiRole
from util.safeHttpUtil import create_pinned_client_session
from .OpenAiModels import (
    OpenAIFunction,
    OpenAIFunctionParameter,
    OpenAIMessage,
    OpenAIRequest,
    OpenAIResponse,
    OpenAITool,
)


logger = logging.getLogger(__name__)
_REDACTED_HEADER_KEYS = {"authorization", "api-key", "x-api-key", "proxy-authorization"}

# M16：litellm.acompletion 显式请求超时（秒）。仅靠会话级 ClientTimeout(total=600)
# 时，慢上游会长时间占用 ServiceRequestGate 并发槽（默认 max_concurrency=5，5 个挂起即耗尽）。
# 非流式一次性返回，超时下调更激进；流式为长连接（生成期间持续产出），给更宽裕的上限。
_NON_STREAM_REQUEST_TIMEOUT_SECONDS = 180.0
_STREAM_REQUEST_TIMEOUT_SECONDS = 600.0


def _patch_responses_api_streaming() -> None:
    """Monkey-patch litellm，修复 Responses API 流式 tool_calls 丢失的问题。

    幂等：通过模块级 _streaming_patched 标志防止重复 patch。
    二次 patch 会导致 _patched 内部 _orig 指向自身，形成无限递归。

    根因：部分代理的 /v1/responses SSE 只发一条 response.completed 事件
    （包含完整 output），而非标准的逐条 response.output_item.added + delta 序列。
    litellm 的 response.completed handler 只设 finish_reason="tool_calls"，不填
    delta.tool_calls，导致 stream_chunk_builder 聚合后 tool_calls 为空。

    修复策略：
    - 抑制中间的 function_call 流式事件（output_item.added / arguments.delta /
      output_item.done），避免 stream_chunk_builder 重复累加 arguments；
    - 在 response.completed 里从 output[] 提取完整 tool_calls 注入 delta。

    这样无论服务端只发 response.completed 还是发完整事件序列，结果均正确。
    """
    from litellm.completion_extras.litellm_responses_transformation.transformation import (
        OpenAiResponsesToChatCompletionStreamIterator,
    )
    from litellm.types.llms.openai import ChatCompletionToolCallFunctionChunk
    from litellm.types.utils import (
        ChatCompletionToolCallChunk,
        Delta,
        ModelResponseStream,
        StreamingChoices,
    )

    global _streaming_patched
    if _streaming_patched:
        return
    _streaming_patched = True

    _orig = OpenAiResponsesToChatCompletionStreamIterator.translate_responses_chunk_to_openai_stream

    def _patched(parsed_chunk):  # type: ignore[no-untyped-def]
        from pydantic import BaseModel
        if isinstance(parsed_chunk, BaseModel):
            parsed_chunk = parsed_chunk.model_dump()

        event_type = parsed_chunk.get("type", "") if isinstance(parsed_chunk, dict) else ""
        if hasattr(event_type, "value"):
            event_type = event_type.value

        # 抑制中间的 function_call 流式事件；tool_calls 统一在 response.completed 注入，
        # 防止 stream_chunk_builder 将 arguments 累加两次。
        if event_type == "response.function_call_arguments.delta":
            return ModelResponseStream(
                choices=[StreamingChoices(index=0, delta=Delta(), finish_reason=None)]
            )
        if event_type in ("response.output_item.added", "response.output_item.done"):
            item = parsed_chunk.get("item", {}) if isinstance(parsed_chunk, dict) else {}
            if isinstance(item, dict) and item.get("type") == "function_call":
                return ModelResponseStream(
                    choices=[StreamingChoices(index=0, delta=Delta(), finish_reason=None)]
                )

        result = _orig(parsed_chunk)

        # 在 response.completed 里从 output[] 提取完整 tool_calls 注入 delta
        if (
            event_type == "response.completed"
            and result.choices
            and result.choices[0].finish_reason == "tool_calls"
            and not result.choices[0].delta.tool_calls
        ):
            response_data = parsed_chunk.get("response", {}) if isinstance(parsed_chunk, dict) else {}
            output_items = response_data.get("output", []) if response_data else []
            tool_calls = []
            tool_call_index = 0
            for item in output_items:
                if not isinstance(item, dict) or item.get("type") != "function_call":
                    continue
                tool_calls.append(
                    ChatCompletionToolCallChunk(
                        id=item.get("call_id"),
                        index=tool_call_index,
                        type="function",
                        function=ChatCompletionToolCallFunctionChunk(
                            name=item.get("name"),
                            arguments=item.get("arguments", "{}"),
                        ),
                    )
                )
                tool_call_index += 1
            if tool_calls:
                result.choices[0].delta.tool_calls = tool_calls  # type: ignore[assignment]

        return result

    OpenAiResponsesToChatCompletionStreamIterator.translate_responses_chunk_to_openai_stream = staticmethod(_patched)  # type: ignore[method-assign]


def init() -> None:
    """初始化 llmApiUtil。使用 litellm 后，此方法主要用于设置全局配置。"""

    # 在这里设置 litellm 的全局配置，例如

    # 关闭所有的调试信息和内置的 print 提示（解决 Provider List 等刷屏问题）
    litellm.suppress_debug_info = True

    # 确保详细模式被关闭
    litellm.set_verbose = False

    # 自动丢弃模型不支持的参数（如 GPT-5 不支持 temperature != 1）
    litellm.drop_params = True

    # 修复 Responses API 流式 tool_calls 丢失问题（幂等：仅首次 patch）
    _patch_responses_api_streaming()


# 幂等标志：防止多次调用 init() 时重复 patch 导致无限递归
_streaming_patched = False


def _clean_base_url(url: str) -> str:
    """清理 base_url，移除末尾可能存在的 /chat/completions 路径，防止 litellm 重复拼接。"""
    if not url:
        return url
    
    base_url = url
    if base_url.endswith("/chat/completions"):
        base_url = base_url[:-len("/chat/completions")]
    elif base_url.endswith("/chat/completions/"):
        base_url = base_url[:-len("/chat/completions/")]
    
    return base_url.rstrip("/")


def _build_request_payload(request: OpenAIRequest) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]] | None]:
    model_name = request.model
    messages = [m.to_dict() for m in request.messages]
    tools: list[dict[str, Any]] | None = None
    if request.tools:
        tools = [t.model_dump(exclude_none=True) for t in request.tools]
    return model_name, messages, tools


def _sanitize_headers(headers: dict[str, str] | None) -> dict[str, str] | None:
    if headers is None:
        return None
    sanitized: dict[str, str] = {}
    for key, value in headers.items():
        if key.lower() in _REDACTED_HEADER_KEYS or "token" in key.lower():
            sanitized[key] = "***"
        else:
            sanitized[key] = value
    return sanitized


def _to_log_data(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=False)
    if isinstance(value, dict):
        return {k: _to_log_data(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_log_data(v) for v in value]
    return value


def _to_log_json(value: Any) -> str:
    return json.dumps(_to_log_data(value), ensure_ascii=False, default=str)


def _request_payload_for_log(request: OpenAIRequest, *, stream: bool) -> dict[str, Any]:
    payload = request.model_dump(mode="json", exclude_none=True)
    payload["stream"] = stream
    return payload


# LiteLLM 会在这两个位置自动注入 cache_control: ephemeral，触发 Anthropic prompt cache。
# 对不支持缓存的 provider，LiteLLM 会静默忽略此参数。
_CACHE_INJECTION_POINTS = [
    {"location": "message", "role": "system"},   # system prompt 通常最稳定，优先缓存
    {"location": "message", "index": -1},        # 最后一条消息作为第二个缓存边界
]


def _log_raw_response(error: Exception, request_id: str, stream: bool) -> None:
    """当 LLM 请求异常时，尝试从异常链中提取并记录上游 API 的原始响应体。

    部分上游 API（如 DeepSeek）在特定错误场景下会返回非标准 JSON 响应，
    导致 SDK 的 JSON 解析失败（如 'Expecting value: line 1 column 67'）。
    此函数从异常对象中提取 httpx.Response 和 body 信息，记录到日志以便排查。

    此函数绝不抛出异常——它是诊断辅助函数，不应影响主流程的错误传播。
    """
    try:
        raw_body = None
        status_code = None
        response_url = None

        # 从异常链中寻找原始响应信息
        current = error
        while current is not None:
            # litellm BadRequestError 等异常携带 response 和 body 属性
            response_obj = getattr(current, "response", None)
            if response_obj is not None:
                try:
                    status_code = getattr(response_obj, "status_code", None)
                    response_url = str(getattr(response_obj, "url", ""))
                    # 尝试读取原始响应体
                    raw_body = getattr(response_obj, "_content", None)
                    if raw_body is None:
                        raw_body = getattr(response_obj, "text", None)
                    elif isinstance(raw_body, bytes):
                        raw_body = raw_body.decode("utf-8", errors="replace")
                except Exception:
                    pass

            # litellm 异常有 body 属性（dict 或原始内容）
            body = getattr(current, "body", None)
            if body is not None and raw_body is None:
                try:
                    if isinstance(body, (dict, list)):
                        raw_body = json.dumps(body, ensure_ascii=False, default=str)
                    elif isinstance(body, str):
                        raw_body = body
                    elif isinstance(body, bytes):
                        raw_body = body.decode("utf-8", errors="replace")
                except Exception:
                    raw_body = f"<unserializable body, type={type(body).__name__}>"

            if raw_body is not None:
                break

            current = current.__cause__ or current.__context__  # type: ignore[assignment]

        if raw_body is not None or status_code is not None:
            # 截断过长的响应体，避免日志膨胀
            if isinstance(raw_body, str) and len(raw_body) > 4096:
                raw_body = raw_body[:4096] + f"... (truncated, total {len(raw_body)} bytes)"
            logger.error(
                "LLM upstream raw response: request_id=%s, stream=%s, status_code=%s, url=%s, raw_body=%s",
                request_id, stream, status_code, response_url, raw_body,
            )
        else:
            logger.warning(
                "LLM upstream raw response unavailable: request_id=%s, stream=%s, error_type=%s",
                request_id, stream, type(error).__name__,
            )
    except Exception:
        # 诊断函数绝不能影响主流程，任何异常都静默吞掉
        logger.warning(
            "LLM upstream raw response logging failed: request_id=%s, stream=%s",
            request_id, stream,
            exc_info=True,
        )

_AGENT_PROBE_TOOLS = [
    OpenAITool(
        function=OpenAIFunction(
            name="send_chat_msg",
            description="向聊天窗口发送消息",
            parameters=OpenAIFunctionParameter(
                type="object",
                properties={
                    "room_name": {"type": "string", "description": "要发送消息的窗口名称"},
                    "msg": {"type": "string", "description": "要发送的消息"},
                },
                required=["room_name", "msg"],
            ),
        )
    ),
    OpenAITool(
        function=OpenAIFunction(
            name="finish_action",
            description="结束行动",
            parameters=OpenAIFunctionParameter(
                type="object",
                properties={},
                required=[],
            ),
        )
    ),
]


def build_agent_probe_request(
    *,
    model: str,
    provider_params: dict[str, Any] | None = None,
) -> OpenAIRequest:
    """构造一个尽量贴近真实 Agent 推理路径的最小探测请求。"""
    return OpenAIRequest(
        model=model,
        messages=[
            OpenAIMessage.text(
                OpenaiApiRole.SYSTEM,
                "你是一个团队协作 Agent。你需要通过工具完成行动，并在结束时调用 finish_action。",
            ),
            OpenAIMessage.text(
                OpenaiApiRole.USER,
                "请做一次最小响应。如果你可以调用工具，请自行决定是否调用；完成后结束行动。",
            ),
        ],
        max_tokens=16,
        stream=True,
        tools=_AGENT_PROBE_TOOLS,
        tool_choice=None,
        prompt_cache=True,
        provider_params=provider_params or {},
    )


# provider_params 白名单：仅允许这些 key 透传给 litellm.acompletion。
# 防止用户配置的 provider_params 覆盖 api_base/api_key/custom_llm_provider
# 等内部参数，导致 SSRF 或鉴权绕过。
_ALLOWED_PROVIDER_PARAM_KEYS = frozenset({
    "tavily_api_key",
    "thinking",
    "max_tokens",
    "temperature",
    "top_p",
    "stop",
    "user",
    "response_format",
    "seed",
    "frequency_penalty",
    "presence_penalty",
    "logit_bias",
    "n",
    "stream_options",
    # GPT-5 / o1 系列参数
    "reasoning_effort",      # GPT-5: "minimal" | "low" | "medium" | "high"
    "verbosity",             # GPT-5: "low" | "medium" | "high"
    # Claude 参数
    "thinking_budget",       # Claude thinking budget tokens
    # DeepSeek 参数
    "reasoning",             # DeepSeek R1 reasoning mode
})


_SECURE_SESSION_PROVIDERS = frozenset({"openai", "deepseek", "anthropic", "gemini"})


def _build_secure_litellm_client(
    base_url: str,
    custom_llm_provider: str | None,
) -> tuple[Any, AsyncHTTPHandler | None]:
    """Build the pinned transport used by every normal Agent inference request.

    LiteLLM 1.84 routes OpenAI-compatible providers through ``shared_session``.
    Anthropic and Gemini accept an ``AsyncHTTPHandler`` instead, so both forms
    are supplied from the same pinned aiohttp session. Unknown provider adapters
    are rejected because they may silently ignore both hooks and resolve DNS again.
    """
    provider = (custom_llm_provider or "").strip().lower()
    if provider not in _SECURE_SESSION_PROVIDERS:
        raise ValueError(f"不支持安全固定 DNS 的 LLM provider: {provider or '未指定'}")
    session = create_pinned_client_session(
        base_url, field_name="LLM base URL", allow_test_loopback=True, allow_private=True
    )
    # OpenAI-compatible adapters expect ``client`` to be an AsyncOpenAI object;
    # passing LiteLLM's HTTP handler there breaks the SDK path. They consume
    # ``shared_session`` directly. Anthropic/Gemini adapters accept the handler.
    #
    # H10 (SSRF pinning fail-open) — for openai/deepseek DNS pinning relies ENTIRELY
    # on LiteLLM (>=1.84) consuming ``shared_session`` (our pinned aiohttp session)
    # for the outbound request. This is an internal, undocumented LiteLLM contract:
    # if a future version stops reusing ``shared_session`` it would build its own
    # httpx client and re-resolve DNS, silently defeating ``_PinnedResolver`` (DNS
    # rebinding window). We cannot inject an httpx-based pinned client here because
    # ``create_pinned_client_session`` yields an aiohttp session, not an httpx one.
    # The assertion below at least guarantees the pinned session was created; the
    # remaining reliance is documented and should be covered by an integration test
    # asserting outbound traffic goes through the pinned resolver.
    assert session is not None, "pinned aiohttp session 必须创建成功，否则 openai/deepseek DNS pinning 会 fail-open"
    safe_client = None if provider in {"openai", "deepseek"} else AsyncHTTPHandler(shared_session=session)
    return session, safe_client


def _build_litellm_extra_params(request: OpenAIRequest) -> dict[str, Any]:
    extra_params: dict[str, Any] = {}
    if request.prompt_cache:
        extra_params["cache_control_injection_points"] = _CACHE_INJECTION_POINTS

    # 白名单过滤：仅允许安全的 provider_params 透传
    for key, value in (request.provider_params or {}).items():
        if key in _ALLOWED_PROVIDER_PARAM_KEYS:
            extra_params[key] = value
    return extra_params


async def send_request_stream(
    request: OpenAIRequest,
    url: str,
    api_key: str,
    custom_llm_provider: str | None = None,
    extra_headers: dict[str, str] | None = None,
    on_chunk: Callable[[ModelResponseStream], Awaitable[None] | None] | None = None,
    request_id: str = "",
) -> OpenAIResponse:
    """流式请求上游模型，并在本地聚合为完整 OpenAIResponse。

    若提供 on_chunk，每收到一个 chunk 后立即回调（支持同步和异步回调）。
    """
    model_name, messages, tools = _build_request_payload(request)
    base_url = _clean_base_url(url)
    logger.info(
        "LLM upstream request start: request_id=%s, stream=%s, provider=%s, base_url=%s, message_count=%d, tool_count=%d, prompt_cache=%s",
        request_id, True, custom_llm_provider, base_url, len(messages), len(tools or []), request.prompt_cache,
    )
    # H9：完整请求正文（system prompt + 全部历史 + 工具入参 + 自定义头）仅在 DEBUG 落盘，
    # 生产默认 INFO 只记元数据，避免对话/业务数据长期沉淀磁盘。
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "LLM upstream request payload: request_id=%s, stream=%s, extra_headers=%s, payload=%s",
            request_id, True, _to_log_json(_sanitize_headers(extra_headers)),
            _to_log_json(_request_payload_for_log(request, stream=True)),
        )

    safe_session, safe_client = _build_secure_litellm_client(base_url, custom_llm_provider)
    stream_resp: ModelResponse | CustomStreamWrapper | None = None
    try:
        extra_params = _build_litellm_extra_params(request)
        stream_resp = await litellm.acompletion(
            model=model_name,
            custom_llm_provider=custom_llm_provider,
            messages=messages,
            api_key=api_key,
            base_url=base_url,
            tools=tools,
            tool_choice=request.tool_choice,
            extra_headers=extra_headers,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            stream=True,
            timeout=_STREAM_REQUEST_TIMEOUT_SECONDS,
            shared_session=safe_session,
            **({"client": safe_client} if safe_client is not None else {}),
            **extra_params,
        )
        if not isinstance(stream_resp, CustomStreamWrapper):
            raise TypeError(f"期望流式响应类型 CustomStreamWrapper，实际为: {type(stream_resp).__name__}")

        chunks: list[ModelResponseStream] = []
        try:
            async for chunk in stream_resp:
                if not isinstance(chunk, ModelResponseStream):
                    raise TypeError(f"期望流式 chunk 类型 ModelResponseStream，实际为: {type(chunk).__name__}")
                chunks.append(chunk)
                # H9：逐 chunk 全文仅 DEBUG 落盘，删除 INFO 级逐 chunk 正文，
                # 避免放大对话数据暴露面与磁盘占用。
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "LLM upstream stream chunk: request_id=%s, chunk_index=%d, payload=%s",
                        request_id, len(chunks), _to_log_json(chunk),
                    )
                if on_chunk is not None:
                    result = on_chunk(chunk)
                    if inspect.isawaitable(result):
                        await result
        finally:
            # 确保流式响应的底层连接被关闭，防止中途异常时 httpx/aiohttp 连接泄漏。
            # litellm CustomStreamWrapper 底层持有 httpx Response，需显式 aclose。
            close = getattr(stream_resp, "aclose", None)
            if close is not None:
                try:
                    await close()
                except Exception:
                    pass

        merged: ModelResponse | TextCompletionResponse | None = litellm.stream_chunk_builder(chunks=chunks, messages=messages)
        if merged is None:
            raise RuntimeError("流式聚合失败：未生成完整响应")
        if isinstance(merged, TextCompletionResponse):
            raise TypeError("流式聚合返回了 TextCompletionResponse；当前仅支持 ChatCompletion 的 ModelResponse")
        if not isinstance(merged, ModelResponse):
            raise TypeError(f"流式聚合返回了未知类型: {type(merged).__name__}")

        logger.info(
            "LLM upstream request success: request_id=%s, stream=%s, chunk_count=%d",
            request_id, True, len(chunks),
        )
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "LLM upstream response payload: request_id=%s, stream=%s, payload=%s",
                request_id, True, _to_log_json(merged),
            )
        return OpenAIResponse.model_validate(merged.model_dump(exclude_none=False))
    except Exception as e:
        _log_raw_response(e, request_id, stream=True)
        logger.exception("LLM upstream request failed: request_id=%s, stream=%s", request_id, True)
        raise
    finally:
        await safe_session.close()


async def send_request_non_stream(
    request: OpenAIRequest,
    url: str,
    api_key: str,
    custom_llm_provider: str | None = None,
    extra_headers: dict[str, str] | None = None,
    request_id: str = "",
) -> OpenAIResponse:
    """非流式请求上游模型，直接返回完整 OpenAIResponse。"""
    model_name, messages, tools = _build_request_payload(request)
    base_url = _clean_base_url(url)
    logger.info(
        "LLM upstream request start: request_id=%s, stream=%s, provider=%s, base_url=%s, message_count=%d, tool_count=%d, prompt_cache=%s",
        request_id, False, custom_llm_provider, base_url, len(messages), len(tools or []), request.prompt_cache,
    )
    # H9：完整请求正文仅 DEBUG 落盘，生产 INFO 只记元数据。
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "LLM upstream request payload: request_id=%s, stream=%s, extra_headers=%s, payload=%s",
            request_id, False, _to_log_json(_sanitize_headers(extra_headers)),
            _to_log_json(_request_payload_for_log(request, stream=False)),
        )

    safe_session, safe_client = _build_secure_litellm_client(base_url, custom_llm_provider)
    try:
        extra_params = _build_litellm_extra_params(request)
        response: ModelResponse | CustomStreamWrapper = await litellm.acompletion(
            model=model_name,
            custom_llm_provider=custom_llm_provider,
            messages=messages,
            api_key=api_key,
            base_url=base_url,
            tools=tools,
            tool_choice=request.tool_choice,
            extra_headers=extra_headers,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            stream=False,
            timeout=_NON_STREAM_REQUEST_TIMEOUT_SECONDS,
            shared_session=safe_session,
            **({"client": safe_client} if safe_client is not None else {}),
            **extra_params,
        )
        if not isinstance(response, ModelResponse):
            raise TypeError(f"期望非流式响应类型 ModelResponse，实际为: {type(response).__name__}")
        logger.info(
            "LLM upstream request success: request_id=%s, stream=%s",
            request_id, False,
        )
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "LLM upstream response payload: request_id=%s, stream=%s, payload=%s",
                request_id, False, _to_log_json(response),
            )
        return OpenAIResponse.model_validate(response.model_dump(exclude_none=False))
    except Exception as e:
        _log_raw_response(e, request_id, stream=False)
        logger.exception("LLM upstream request failed: request_id=%s, stream=%s", request_id, False)
        raise
    finally:
        await safe_session.close()
