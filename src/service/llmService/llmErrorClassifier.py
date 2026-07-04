from constants import LlmErrorCategory

from litellm.exceptions import (
    APIConnectionError,
    AuthenticationError,
    BadRequestError,
    ContentPolicyViolationError,
    ContextWindowExceededError,
    InternalServerError,
    InvalidRequestError,
    PermissionDeniedError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
)

# 上下文超长关键词（部分 provider 不抛 ContextWindowExceededError，只返回文本）
# 注：移除过宽的 "max_tokens"/"token limit"，它们在输出超限或参数错误时也会出现，
# 误判为 context overflow 会触发无意义的 compact。
_CONTEXT_WINDOW_KEYWORDS = (
    "context_length_exceeded",
    "maximum context length",
    "prompt is too long",
    "input is too long",
    "input too long",
    "exceeds the context window",
    "too many tokens",
    "context window",
)

# 编程错误类型：确定性失败，重试无意义，不应归入可重试分类。
_PROGRAMMING_ERROR_TYPES = (TypeError, AttributeError, KeyError, ValueError)

# 可重试的错误分类。
# 注：UNKNOWN 不在可重试集合中——它是兜底分类，可能含编程错误，
# 重试只会浪费时间（最长 126 秒）。
RETRYABLE_CATEGORIES = {
    LlmErrorCategory.RATE_LIMITED,
    LlmErrorCategory.SERVER_ERROR,
    LlmErrorCategory.NETWORK_ERROR,
}


def classify_llm_error(error: Exception) -> LlmErrorCategory:
    """将 LLM 调用异常分类为 LlmErrorCategory 枚举值。"""
    # 编程错误优先判定为 INVALID_REQUEST（不可重试），避免 TypeError/AttributeError
    # 等被当作 UNKNOWN 兜底后仍可能被误用。
    if isinstance(error, _PROGRAMMING_ERROR_TYPES):
        return LlmErrorCategory.INVALID_REQUEST

    if isinstance(error, ContextWindowExceededError):
        return LlmErrorCategory.CONTEXT_WINDOW

    if isinstance(error, (AuthenticationError, PermissionDeniedError)):
        return LlmErrorCategory.AUTH_ERROR

    if isinstance(error, ContentPolicyViolationError):
        return LlmErrorCategory.CONTENT_POLICY

    if isinstance(error, RateLimitError):
        return LlmErrorCategory.RATE_LIMITED

    if isinstance(error, (InternalServerError, ServiceUnavailableError)):
        return LlmErrorCategory.SERVER_ERROR

    if isinstance(error, (APIConnectionError, Timeout)):
        return LlmErrorCategory.NETWORK_ERROR

    if isinstance(error, (BadRequestError, InvalidRequestError)):
        error_text = str(error).lower()
        if any(kw in error_text for kw in _CONTEXT_WINDOW_KEYWORDS):
            return LlmErrorCategory.CONTEXT_WINDOW
        return LlmErrorCategory.INVALID_REQUEST

    # 兜底：关键词匹配上下文超长
    error_text = str(error).lower()
    if any(kw in error_text for kw in _CONTEXT_WINDOW_KEYWORDS):
        return LlmErrorCategory.CONTEXT_WINDOW

    return LlmErrorCategory.UNKNOWN
