"""Unit tests for llmService 首选 + 兜底 failover 服务链构建（审计 #3）。"""
import pytest

from service.llmService import core as llm_core
from util import configUtil
from util.configTypes import AppConfig, SettingConfig


def _config(*, default: str | None, services: list[dict], fallback: list[str]) -> AppConfig:
    return AppConfig(setting=SettingConfig(
        default_llm_server=default,
        llm_services=services,
        fallback_llm_servers=fallback,
    ))


def _svc(name: str, enable: bool = True) -> dict:
    return {
        "name": name,
        "enable": enable,
        "base_url": f"http://localhost/{name}/v1/chat/completions",
        "api_key": f"key-{name}",
        "type": "openai-compatible",
    }


def test_chain_primary_then_fallbacks_in_order(monkeypatch):
    monkeypatch.setattr(configUtil, "get_app_config", lambda: _config(
        default="primary",
        services=[_svc("primary"), _svc("backup1"), _svc("backup2")],
        fallback=["backup1", "backup2"],
    ))
    chain = llm_core._resolve_llm_service_chain(team_config=None)
    assert [s.name for s in chain] == ["primary", "backup1", "backup2"]


def test_chain_dedups_primary_appearing_in_fallback(monkeypatch):
    monkeypatch.setattr(configUtil, "get_app_config", lambda: _config(
        default="primary",
        services=[_svc("primary"), _svc("backup1")],
        fallback=["primary", "backup1"],  # primary 重复出现应被去重
    ))
    chain = llm_core._resolve_llm_service_chain(team_config=None)
    assert [s.name for s in chain] == ["primary", "backup1"]


def test_chain_skips_disabled_and_unknown_fallbacks(monkeypatch):
    monkeypatch.setattr(configUtil, "get_app_config", lambda: _config(
        default="primary",
        services=[_svc("primary"), _svc("backup1", enable=False)],
        fallback=["backup1", "does-not-exist", "backup1"],
    ))
    chain = llm_core._resolve_llm_service_chain(team_config=None)
    # backup1 未启用、does-not-exist 不存在，均跳过；仅剩 primary
    assert [s.name for s in chain] == ["primary"]


def test_chain_empty_when_no_service_available(monkeypatch):
    monkeypatch.setattr(configUtil, "get_app_config", lambda: _config(
        default=None, services=[], fallback=["whatever"],
    ))
    chain = llm_core._resolve_llm_service_chain(team_config=None)
    assert chain == []
