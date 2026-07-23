"""compact — Token 预算、overflow 识别与 compact 执行。"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
from typing import Any

import litellm

from model.coreModel.gtCoreChatModel import GtCoreAgentDialogContext
from service import llmService
from service.agentService import promptBuilder
from util import llmApiUtil
from util.configTypes import LlmServiceConfig

logger = logging.getLogger(__name__)

# 系统内置模型上下文长度默认表（仅用于配置未显式覆盖时的兜底）
DEFAULT_MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    "glm-4.7": 128000,
    "qwen-plus": 131072,
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-4": 8192,
    "gpt-4-turbo": 128000,
    "claude-3-5-sonnet-20241022": 200000,
    "claude-sonnet-4-20250514": 200000,
    "deepseek-chat": 128000,
}

# 用于识别上下文超长的错误关键词
# 注：移除过宽的 "max_tokens"/"token limit"，与 llmErrorClassifier 保持一致。
_OVERFLOW_KEYWORDS = (
    "context_length_exceeded",
    "maximum context length",
    "prompt is too long",
    "input is too long",
    "input too long",
    "exceeds the context window",
    "too many tokens",
    "context window",
)

# ─── 阈值计算 ────────────────────────────────────────────

def calc_hard_limit_tokens(model: str, llm_config: LlmServiceConfig) -> int:
    """计算模型当前请求允许使用的最大 prompt token。"""
    context_window = DEFAULT_MODEL_CONTEXT_WINDOWS.get(model, llm_config.context_window_tokens)
    return context_window - llm_config.reserve_output_tokens


def calc_compact_trigger_tokens(model: str, llm_config: LlmServiceConfig) -> int:
    """计算 compact 触发阈值（token 数）。"""
    return math.floor(calc_hard_limit_tokens(model, llm_config) * llm_config.compact_trigger_ratio)


# ─── token 估算 ──────────────────────────────────────────

# estimate_tokens 结果缓存：litellm.token_counter 为 CPU 密集操作，同一份
# 消息在 pre-check / post-check / overflow 三条路径上会被反复估算，缓存可显著
# 降低事件循环阻塞（审计 M5）。以内容签名为键，超过上限时整体清空（简单有界）。
_TOKEN_ESTIMATE_CACHE: dict[str, int] = {}
_TOKEN_ESTIMATE_CACHE_MAX = 512


def _build_msg_dicts(
    messages: list[llmApiUtil.OpenAIMessage],
    system_prompt: str | None,
) -> list[dict[str, Any]]:
    msg_dicts: list[dict[str, Any]] = []
    if system_prompt:
        msg_dicts.append({"role": "system", "content": system_prompt})
    for msg in messages:
        msg_dicts.append(msg.to_dict())
    return msg_dicts


def _cache_key(model: str, msg_dicts: list[dict[str, Any]]) -> str:
    """基于模型名 + 消息内容的稳定签名，用作 token 估算缓存键。"""
    payload = json.dumps(msg_dicts, sort_keys=True, ensure_ascii=False)
    h = hashlib.sha1()
    h.update(model.encode("utf-8", errors="ignore"))
    h.update(b"\x00")
    h.update(payload.encode("utf-8", errors="ignore"))
    return h.hexdigest()


def estimate_tokens(
    model: str,
    messages: list[llmApiUtil.OpenAIMessage],
    system_prompt: str | None = None,
) -> int:
    """估算消息列表的 token 数量，使用 litellm.token_counter（带结果缓存）。

    注意：此函数为同步 CPU 密集调用，位于事件循环协程中会阻塞其他 Agent。
    异步上下文应优先使用 `estimate_tokens_async`（审计 M5）。
    """
    try:
        msg_dicts = _build_msg_dicts(messages, system_prompt)
        key = _cache_key(model, msg_dicts)
        cached = _TOKEN_ESTIMATE_CACHE.get(key)
        if cached is not None:
            return cached
        result = litellm.token_counter(model=model, messages=msg_dicts)
        if len(_TOKEN_ESTIMATE_CACHE) >= _TOKEN_ESTIMATE_CACHE_MAX:
            _TOKEN_ESTIMATE_CACHE.clear()
        _TOKEN_ESTIMATE_CACHE[key] = result
        return result
    except Exception as e:
        logger.warning("token 估算失败，回退到字符估算: error=%s", e)
        return estimate_token_by_char(messages, system_prompt)


async def estimate_tokens_async(
    model: str,
    messages: list[llmApiUtil.OpenAIMessage],
    system_prompt: str | None = None,
) -> int:
    """`estimate_tokens` 的异步封装：在线程池执行 CPU 密集的 token_counter，
    避免大历史直接在事件循环里估算阻塞全体 Agent 推理与 WS 响应（审计 M5）。"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, estimate_tokens, model, messages, system_prompt)



def estimate_token_by_char(messages: list[llmApiUtil.OpenAIMessage], system_prompt: str | None = None) -> int:
    """字符数的粗略估算，作为 litellm 失败时的兜底。

    中文 1 字符约 1-2 token，英文约 4 字符/token。这里按 1.5 字符/token 折算
    （混合中英文场景的经验值），避免 litellm 失败时严重低估导致 compact
    触发滞后、真实上下文超长。
    正确处理 content 为 list[block] 的多模态消息格式。
    """
    def _content_len(content) -> int:
        """计算 content 的字符长度，兼容 str 和 list[block] 格式。"""
        if content is None:
            return 0
        if isinstance(content, str):
            return len(content)
        if isinstance(content, (list, tuple)):
            # 多模态 block 列表：递归提取 text 字段
            total = 0
            for block in content:
                if isinstance(block, str):
                    total += len(block)
                elif isinstance(block, dict):
                    total += len(str(block.get("text") or ""))
                else:
                    total += len(str(block))
            return total
        return len(str(content))

    total_chars = len(system_prompt or "")
    for msg in messages:
        total_chars += _content_len(msg.content)
        if msg.tool_calls:
            for tc in msg.tool_calls:
                total_chars += len(tc.function_args)
    return max(1, int(total_chars / 1.5))


def is_context_overflow_error(error: Exception) -> bool:
    """判断异常是否属于"上下文超长"错误。"""
    error_text = str(error).lower()
    return any(kw in error_text for kw in _OVERFLOW_KEYWORDS)


# ─── compact 执行 ─────────────────────────────────────────

_TRUNCATE_MARKER = "\n\n[...内容过长，已按 token 上限硬截断...]\n\n"


def _count_text_tokens(model: str, text: str) -> int:
    """估算单段文本的 token 数（失败时按字符兜底）。"""
    try:
        return litellm.token_counter(model=model, text=text)
    except Exception:
        return max(1, int(len(text) / 1.5))


def _hard_truncate_text_to_tokens(text: str, model: str, max_tokens: int) -> str:
    """将单段文本按 token 上限硬截断，保证收敛（审计 M14）。

    先按 token/字符比例估算保留长度，再迭代收敛（有界次数），避免超长单条消息
    在 compact 时无法压缩到目标预算，导致下游请求 400。
    """
    if not text or max_tokens <= 0:
        return text
    tokens = _count_text_tokens(model, text)
    if tokens <= max_tokens:
        return text

    ratio = max_tokens / max(1, tokens)
    keep_chars = max(1, int(len(text) * ratio * 0.9))
    for _ in range(12):
        candidate = text[:keep_chars] + _TRUNCATE_MARKER
        if _count_text_tokens(model, candidate) <= max_tokens:
            return candidate
        keep_chars = max(1, int(keep_chars * 0.8))
        if keep_chars <= 1:
            break
    return text[:1] + _TRUNCATE_MARKER


def _truncate_messages_to_tokens(
    messages: list[llmApiUtil.OpenAIMessage], model: str, max_tokens: int
) -> list[llmApiUtil.OpenAIMessage]:
    """批量硬截断（同步、CPU 密集）：供事件循环通过 run_in_executor 调用。"""
    return [_truncate_message_to_tokens(m, model, max_tokens) for m in messages]


def _truncate_message_to_tokens(
    msg: llmApiUtil.OpenAIMessage, model: str, max_tokens: int
) -> llmApiUtil.OpenAIMessage:
    """若单条消息的 content 超过 token 预算，则硬截断后返回副本；否则原样返回。"""
    content = msg.content
    if not isinstance(content, str) or not content:
        return msg
    if _count_text_tokens(model, content) <= max_tokens:
        return msg
    truncated = _hard_truncate_text_to_tokens(content, model, max_tokens)
    logger.warning(
        "compact 源消息超长，token 级硬截断: role=%s, before_chars=%d, after_chars=%d, max_tokens=%d",
        msg.role, len(content), len(truncated), max_tokens,
    )
    return msg.model_copy(update={"content": truncated})


async def compact_messages(
    messages: list[llmApiUtil.OpenAIMessage],
    system_prompt: str,
    model: str,
    tools: list[llmApiUtil.OpenAITool] | None = None,
    max_tokens: int = 13107,
    team_config: dict | None = None,
    per_message_max_tokens: int | None = None,
) -> str:
    """压缩消息列表，返回已包含引导语的摘要文本，失败时抛出异常。

    Args:
        messages: 待压缩的消息列表
        system_prompt: 系统提示（用于正确理解上下文）
        model: 模型名称
        tools: 透传当前工具列表，以保持请求形态稳定
        max_tokens: 摘要最大 token 数，建议为 context_window_tokens 的 10%
        team_config: 团队级配置 dict（含 llm_service_name），传入时使用团队级 LLM 服务
        per_message_max_tokens: 单条源消息 token 硬上限；传入时对超长单条消息做 token
            级硬截断，保证 compact 请求可收敛，避免超长单条消息触发下游 400（审计 M14）

    Returns:
        摘要文本（已包含引导语）

    Raises:
        RuntimeError: LLM 推理失败、返回为空、或返回了 tool_calls
    """
    if per_message_max_tokens is not None and per_message_max_tokens > 0:
        # token_counter 为 CPU 密集操作，整批下沉线程池，避免阻塞事件循环（审计 M5 截断路径）
        loop = asyncio.get_running_loop()
        messages = await loop.run_in_executor(
            None, _truncate_messages_to_tokens, messages, model, per_message_max_tokens
        )
    instruction = promptBuilder.build_compact_instruction(max_tokens)
    ctx = GtCoreAgentDialogContext(
        system_prompt=system_prompt,
        messages=messages + [llmApiUtil.OpenAIMessage.text(llmApiUtil.OpenaiApiRole.USER, instruction)],
        tools=tools,
        tool_choice="none",
    )
    infer_result = await llmService.infer(model, ctx, team_config=team_config)

    if infer_result.ok is False:
        raise RuntimeError(infer_result.error_message or "LLM inference failed during compact")

    if infer_result.response is None:
        raise RuntimeError("LLM returned empty response during compact")
    response_message = infer_result.response.choices[0].message

    if response_message.tool_calls:
        raise RuntimeError("Model returned tool_calls instead of summary during compact")
    summary = response_message.content or ""
    return promptBuilder.build_compact_resume_prompt(summary)
