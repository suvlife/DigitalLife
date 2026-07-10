import os
from types import SimpleNamespace

import pytest

import appPaths
from constants import DriverType
from service.agentService.driver.base import AgentDriverConfig
from service.agentService.driver.factory import build_agent_driver
from service.agentService.driver.nativeDriver import NativeAgentDriver


def test_gtsp_platform_mapping() -> None:
    assert appPaths.get_gtsp_platform_id(system="Darwin", machine="arm64") == "darwin-arm64"
    assert appPaths.get_gtsp_platform_id(system="Linux", machine="x86_64") == "linux-amd64"
    assert appPaths.get_gtsp_platform_id(system="Windows", machine="AMD64") == "windows-amd64"


def test_gtsp_unsupported_platform_has_actionable_error() -> None:
    with pytest.raises(RuntimeError, match="Unsupported GTSP platform"):
        appPaths.get_gtsp_platform_id(system="Plan9", machine="mips")


def test_get_gtsp_binary_path_can_return_expected_missing_path(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(appPaths, "ASSETS_DIR", str(tmp_path))
    path = appPaths.get_gtsp_binary_path(require_exists=False)
    assert path.endswith(f"gtsp-{appPaths.get_gtsp_platform_id()}{'.exe' if os.name == 'nt' else ''}")


def test_factory_falls_back_to_native_when_gtsp_missing(monkeypatch) -> None:
    monkeypatch.setattr(appPaths, "gtsp_diagnostic", lambda: {"available": False, "path": "/missing/gtsp"})
    import util.configUtil as configUtil
    fallback = SimpleNamespace(enabled=True, tsp_to_native=True)
    monkeypatch.setattr(configUtil, "get_app_config", lambda: SimpleNamespace(setting=SimpleNamespace(driver_fallback=fallback)))
    host = SimpleNamespace(gt_agent=SimpleNamespace(id=1))
    driver = build_agent_driver(host, AgentDriverConfig(driver_type=DriverType.TSP, options={}))
    assert isinstance(driver, NativeAgentDriver)
    assert driver.config.options["degraded_from"] == "tsp"
