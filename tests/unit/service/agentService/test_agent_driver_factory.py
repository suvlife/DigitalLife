import os
import sys

from constants import DriverType
from service.agentService.driver import normalize_driver_config

if os.name == "posix" and sys.platform == "darwin":
    os.environ.setdefault("OBJC_DISABLE_INITIALIZE_FORK_SAFETY", "YES")


def test_normalize_driver_config_defaults_to_native() -> None:
    cfg = normalize_driver_config({"name": "alice", "model": "test"})
    assert cfg.driver_type == DriverType.NATIVE
    assert cfg.options == {}


def test_normalize_driver_config_supports_claude_sdk_driver_with_allowed_tools() -> None:
    cfg = normalize_driver_config(
        {
            "name": "alice",
            "model": "test",
            "driver": "claude_sdk",
            "allowed_tools": ["Read", "Write"],
        }
    )
    assert cfg.driver_type == DriverType.CLAUDE_SDK
    assert cfg.options == {}


def test_normalize_driver_config_filters_local_and_category_allowed_tools_for_claude_sdk() -> None:
    cfg = normalize_driver_config(
        {
            "name": "alice",
            "model": "test",
            "driver": "claude_sdk",
            "allowed_tools": ["Read", "Category:Read", "get_time", "send_chat_msg"],
        }
    )
    assert cfg.driver_type == DriverType.CLAUDE_SDK
    assert cfg.options == {}


def test_normalize_driver_config_supports_driver_type_enum() -> None:
    cfg = normalize_driver_config(
        {
            "name": "alice",
            "model": "test",
            "driver": DriverType.TSP,
        }
    )
    assert cfg.driver_type == DriverType.TSP
    assert cfg.options == {}
