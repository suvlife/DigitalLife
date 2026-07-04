"""compact — Token 预算、overflow 识别与 compact 执行。"""
from __future__ import annotations

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

def estimate_tokens(
    model: str,
    messages: list[llmApiUtil.OpenAIMessage],
    system_prompt: str | None = None,
) -> int:
    """估算消息列表的 token 数量，使用 litellm.token_counter。"""
    try:
        msg_dicts: list[dict[str, Any]] = []
        if system_prompt:
            msg_dicts.append({"role": "system", "content": system_prompt})
        for msg in messages:
            msg_dicts.append(msg.to_dict())
        return litellm.token_counter(model=model, messages=msg_dicts)
    except Exception as e:
        logger.warning("token 估算失败，回退到字符估算: error=%s", e)
        return estimate_token_by_char(messages, system_prompt)


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

async def compact_messages(
    messages: list[llmApiUtil.OpenAIMessage],
    system_prompt: str,
    model: str,
    tools: list[llmApiUtil.OpenAITool] | None = None,
    max_tokens: int = 13107,
    team_config: dict | None = None,
) -> str:
    """压缩消息列表，返回已包含引导语的摘要文本，失败时抛出异常。

    Args:
        messages: 待压缩的消息列表
        system_prompt: 系统提示（用于正确理解上下文）
        model: 模型名称
        tools: 透传当前工具列表，以保持请求形态稳定
        max_tokens: 摘要最大 token 数，建议为 context_window_tokens 的 10%
        team_config: 团队级配置 dict（含 llm_service_name），传入时使用团队级 LLM 服务

    Returns:
        摘要文本（已包含引导语）

    Raises:
        RuntimeError: LLM 推理失败、返回为空、或返回了 tool_calls
    """
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
