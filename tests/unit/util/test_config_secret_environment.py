import json
from types import SimpleNamespace

from util import configUtil
from util.configTypes import AppConfig, SettingConfig


def test_environment_ghost_secret_is_not_persisted(monkeypatch, tmp_path) -> None:
    setting_path = tmp_path / "setting.json"
    setting_path.write_text(json.dumps({
        "ghost": {"admin_api_key": "file-secret", "content_api_key": "file-content"},
        "llm_services": [],
    }), encoding="utf-8")
    setting = SettingConfig()
    setting.ghost.admin_api_key = "env-secret"
    setting.ghost.content_api_key = "env-content"
    monkeypatch.setenv("GHOST_ADMIN_API_KEY", "env-secret")
    monkeypatch.setenv("GHOST_CONTENT_API_KEY", "env-content")
    monkeypatch.setattr(configUtil, "_cached_config_dir", str(tmp_path))
    monkeypatch.setattr(configUtil, "_cached_app_config", AppConfig(setting=setting))

    configUtil._save_setting_to_file()

    persisted = json.loads(setting_path.read_text(encoding="utf-8"))
    assert persisted["ghost"]["admin_api_key"] == "file-secret"
    assert persisted["ghost"]["content_api_key"] == "file-content"
    assert "env-secret" not in setting_path.read_text(encoding="utf-8")
