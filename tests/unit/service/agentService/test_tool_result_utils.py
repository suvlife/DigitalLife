"""toolResultUtils 纯函数模块的单元测试（拆分 #18 P1）。"""
from service.agentService import toolResultUtils as u


class _ToolCall:
    def __init__(self, name, args):
        self.function_name = name
        self.function_args = args


def test_is_dangerous_command():
    assert u.is_dangerous_command("rm -rf /tmp/x") is True
    assert u.is_dangerous_command("curl https://x.com") is True
    assert u.is_dangerous_command("ls -la") is False
    assert u.is_dangerous_command("echo hello") is False


def test_detect_json_tool_call_in_content():
    assert u.detect_json_tool_call_in_content('{"name": "x"}') is True
    assert u.detect_json_tool_call_in_content('  {"a": 1}  ') is True
    assert u.detect_json_tool_call_in_content('[1,2]') is False
    assert u.detect_json_tool_call_in_content('plain text') is False
    assert u.detect_json_tool_call_in_content('') is False
    assert u.detect_json_tool_call_in_content(None) is False
    assert u.detect_json_tool_call_in_content('{invalid json}') is False


def test_extract_tool_command():
    assert u.extract_tool_command(_ToolCall("execute_bash", '{"command": "ls -la"}')) == "ls -la"
    assert u.extract_tool_command(_ToolCall("execute_bash", '{"command": "  "}')) is None
    assert u.extract_tool_command(_ToolCall("web_search", '{"command": "x"}')) is None
    assert u.extract_tool_command(_ToolCall("execute_bash", 'not json')) is None
    assert u.extract_tool_command(_ToolCall("execute_bash", '{"other": 1}')) is None


def test_extract_tool_arguments():
    assert u.extract_tool_arguments(_ToolCall("x", '{"a": 1}')) == {"a": 1}
    assert u.extract_tool_arguments(_ToolCall("x", '')) is None
    assert u.extract_tool_arguments(_ToolCall("x", 'raw string')) == 'raw string'


def test_truncate_tool_result_for_history():
    long_text = "x" * 7000
    result = {"content": long_text}
    truncated = u.truncate_tool_result_for_history(result, "web_search", max_length=100)
    assert len(truncated["content"]) < 7000
    assert truncated["_history_truncated"] is True
    # 不在截断名单的工具不动
    assert u.truncate_tool_result_for_history({"content": long_text}, "other_tool") == {"content": long_text}
    # 非 dict 原样返回
    assert u.truncate_tool_result_for_history("str", "web_search") == "str"


def test_build_usage():
    usage = u.build_usage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    assert usage.prompt_tokens == 10
    assert usage.completion_tokens == 5
    assert usage.total_tokens == 15
