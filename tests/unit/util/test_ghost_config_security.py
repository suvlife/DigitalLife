from util.configTypes import GhostConfig
from controller.settingController import _apply_ghost_config_patch


def test_empty_keys_preserve_existing_values() -> None:
    ghost = GhostConfig(admin_api_key="admin-secret", content_api_key="content-secret")
    _apply_ghost_config_patch(ghost, {"admin_api_key": "", "content_api_key": ""})
    assert ghost.admin_api_key == "admin-secret"
    assert ghost.content_api_key == "content-secret"


def test_explicit_clear_removes_keys() -> None:
    ghost = GhostConfig(admin_api_key="admin-secret", content_api_key="content-secret")
    _apply_ghost_config_patch(ghost, {
        "clear_admin_api_key": True,
        "clear_content_api_key": True,
    })
    assert ghost.admin_api_key == ""
    assert ghost.content_api_key == ""
