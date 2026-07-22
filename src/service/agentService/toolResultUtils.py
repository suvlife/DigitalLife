"""工具结果与命令处理的纯函数集合（从 AgentTurnRunner 抽离，拆分 #18 P1）。

这些函数均为零 self 状态依赖的纯函数，供 AgentTurnRunner / ToolExecutor /
CompactManager 等共享。抽出后减少主类体量，并便于独立测试。
"""
from __future__ import annotations

import json
from typing import Any

from model.dbModel.historyUsage import CompactStage, HistoryUsage
from util import llmApiUtil


# 高危命令模式：公网部署时拦截可能危害服务器的命令
_DANGEROUS_COMMAND_PATTERNS = [
    "rm -rf", "rmdir", "mkfs", "dd if=", "shutdown", "reboot", "halt",
    "curl ", "wget ", "nc ", "netcat", "ssh ", "scp ", "rsync ",
    "pip install", "npm install", "apt ", "yum ", "brew ",
    "chmod 777", "chown ", ">/dev/", "mkfifo",
    "python -c", "python3 -c", "eval ", "exec ",
    "`rm", "$(", "base64 -d", "curl|", "wget|",
    "crontab", "systemctl", "service ",
    "kill -9", "pkill", "killall",
    "iptables", "ufw", "firewall",
    "/etc/", "/root/", "/var/", "/tmp/.",
]


def is_dangerous_command(command: str) -> bool:
    """检查命令是否含高危操作。公网部署时拦截可能危害服务器的命令。"""
    cmd_lower = command.lower()
    for pattern in _DANGEROUS_COMMAND_PATTERNS:
        if pattern in cmd_lower:
            return True
    return False


def detect_json_tool_call_in_content(content: str | None) -> bool:
    """检测 LLM 是否将工具调用以 JSON 对象形式写入了 content 字段（而非 tool_calls）。"""
    if not content:
        return False
    stripped = content.strip()
    if not (stripped.startswith("{") and stripped.endswith("}")):
        return False
    try:
        data = json.loads(stripped)
        return isinstance(data, dict)
    except (json.JSONDecodeError, ValueError):
        return False


def extract_tool_command(tool_call: llmApiUtil.OpenAIToolCall) -> str | None:
    """从 execute_bash 工具调用中提取待执行的 shell 命令。"""
    if tool_call.function_name != "execute_bash":
        return None
    try:
        parsed_args = json.loads(tool_call.function_args)
    except Exception:
        return None
    command = parsed_args.get("command")
    if not isinstance(command, str):
        return None
    command = command.strip()
    return command if len(command) > 0 else None


def extract_tool_arguments(tool_call: llmApiUtil.OpenAIToolCall) -> Any:
    """解析工具调用的 JSON 参数；解析失败时返回原始字符串。"""
    raw_args = tool_call.function_args.strip()
    if not raw_args:
        return None
    try:
        return json.loads(raw_args)
    except Exception:
        return raw_args


def truncate_tool_result_for_history(result: dict[str, Any], tool_name: str, max_length: int = 6000) -> dict[str, Any]:
    """对需要存入 history 的工具结果进行截断，避免消耗过多 token。

    完整结果仍保留在 activity 记录中。
    主要截断对象：web_search / web_fetch / read_file / execute_bash / process_output
    """
    if not isinstance(result, dict):
        return result

    truncatable_tools = {"web_search", "web_fetch", "read_file", "execute_bash", "process_output", "grep_search"}
    if tool_name not in truncatable_tools:
        return result

    content_keys = {"content", "message", "results", "stdout", "output"}
    truncated = dict(result)
    was_truncated = False

    for key in content_keys:
        value = truncated.get(key)
        if value is None:
            continue
        text = str(value)
        if len(text) > max_length:
            truncated[key] = text[:max_length] + "\n\n[内容已截断，完整结果可在活动记录中查看]"
            was_truncated = True

    if was_truncated:
        truncated["_history_truncated"] = True
    return truncated


def build_usage(
    *,
    estimated_prompt_tokens: int | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
    compact_stage: CompactStage = "none",
    overflow_retry: bool = False,
) -> HistoryUsage:
    """构造 HistoryUsage 值对象。"""
    return HistoryUsage(
        estimated_prompt_tokens=estimated_prompt_tokens,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        compact_stage=compact_stage,
        overflow_retry=overflow_retry,
    )
