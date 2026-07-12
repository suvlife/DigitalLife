from __future__ import annotations

import json

import pytest

from constants import LlmServiceType
from controller import settingController
from util.configTypes import LlmServiceConfig


@pytest.mark.asyncio
async def test_llm_probe_uses_shared_safe_http_policy(monkeypatch):
    captured = {}

    async def request(method, url, **kwargs):
        captured.update(method=method, url=url, kwargs=kwargs)
        return settingController.safeHttpUtil.SafeHttpResponse(
            200, {"content-type": "application/json"},
            json.dumps({"choices": [{"message": {"content": "OK"}}], "usage": {"total_tokens": 1}}).encode(),
            url,
        )

    monkeypatch.setattr(settingController.safeHttpUtil, "request", request)
    config = LlmServiceConfig(
        name="probe", base_url="https://api.example/v1", api_key="secret",
        type=LlmServiceType.OPENAI_COMPATIBLE, model="model", extra_headers={}, provider_params={},
    )
    result = await settingController._test_llm_service(config)

    assert captured["method"] == "POST"
    assert captured["url"] == "https://api.example/v1/chat/completions"
    assert captured["kwargs"]["field_name"] == "base_url"
    assert captured["kwargs"]["headers"]["Authorization"] == "Bearer secret"
    assert result["test_mode"] == "ssrf_safe_provider_probe"
