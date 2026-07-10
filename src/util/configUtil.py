import glob
import json
import os
import shutil
import threading
from typing import Any, Callable, List

import appPaths
from util.configTypes import (
    RoleTemplatePreset,
    AppConfig,
    SettingConfig,
    TeamPreset,
)

_cached_app_config: AppConfig | None = None
_cached_config_dir: str | None = None
_cached_preset_dir: str | None = None
# 保护 update_setting / _save_setting_to_file 的读改写竞态，
# 防止并发请求交错导致配置丢失。
_setting_lock = threading.Lock()
# 内置默认 Key（用户不可见，不通过 API 返回明文）
_builtin_keys: dict | None = None


def _load_builtin_keys() -> dict:
    """加载内置默认 API Key。从 assets/builtin_keys.json 读取。

    内置 Key 对用户不可见：
    - 不通过 /config/llm_services/list.json 返回明文
    - 用户可自行添加自己的 Key 覆盖内置 Key
    - 内置 LLM 服务在用户未配置任何服务时自动启用
    """
    global _builtin_keys
    if _builtin_keys is not None:
        return _builtin_keys

    builtin_path = os.path.join(appPaths.ASSETS_DIR, "builtin_keys.json")
    if not os.path.isfile(builtin_path):
        _builtin_keys = {}
        return _builtin_keys

    try:
        with open(builtin_path, "r", encoding="utf-8") as f:
            _builtin_keys = json.load(f)
    except Exception:
        _builtin_keys = {}
    return _builtin_keys


def get_builtin_search_keys() -> dict[str, str]:
    """获取内置搜索 API Key（Tavily + Brave）。"""
    builtin = _load_builtin_keys()
    return builtin.get("search_keys", {})


def get_builtin_llm_services() -> list:
    """获取内置 LLM 服务列表。"""
    builtin = _load_builtin_keys()
    return builtin.get("llm_services", [])


def get_builtin_default_llm_server() -> str | None:
    """获取内置默认 LLM 服务名。"""
    builtin = _load_builtin_keys()
    return builtin.get("default_llm_server")


def get_builtin_ghost_config() -> dict:
    """获取无凭据的内置 Ghost 默认配置（仅兼容旧调用）。"""
    builtin = _load_builtin_keys()
    return builtin.get("ghost", {})


def apply_secret_environment_overrides(setting: SettingConfig) -> None:
    """用进程环境变量覆盖敏感配置，且不把环境变量写回 setting.json。"""
    ghost_url = os.environ.get("GHOST_API_URL")
    ghost_admin_key = os.environ.get("GHOST_ADMIN_API_KEY")
    ghost_content_key = os.environ.get("GHOST_CONTENT_API_KEY")
    if ghost_url:
        setting.ghost.api_url = ghost_url.strip()
    if ghost_admin_key:
        setting.ghost.admin_api_key = ghost_admin_key.strip()
    if ghost_content_key:
        setting.ghost.content_api_key = ghost_content_key.strip()
    if os.environ.get("GHOST_ENABLED") is not None:
        setting.ghost.enabled = os.environ["GHOST_ENABLED"].strip().lower() in {"1", "true", "yes", "on"}
    if os.environ.get("GHOST_AUTO_PUBLISH") is not None:
        setting.ghost.auto_publish = os.environ["GHOST_AUTO_PUBLISH"].strip().lower() in {"1", "true", "yes", "on"}

    fallback = os.environ.get("TOGOSPACE_TSP_FALLBACK_NATIVE")
    if fallback is not None:
        setting.driver_fallback.enabled = fallback.strip().lower() in {"1", "true", "yes", "on"}
        setting.driver_fallback.tsp_to_native = setting.driver_fallback.enabled


def _is_running_tests() -> bool:
    """检测当前是否在 pytest 测试环境中运行。"""
    return "PYTEST_CURRENT_TEST" in os.environ


def _resolve_config_dir(config_dir: str | None) -> str:
    if config_dir is not None:
        return os.path.abspath(config_dir)
    return appPaths.CONFIG_DIR


def _resolve_preset_dir() -> str:
    return appPaths.PRESET_DIR


def get_db_path() -> str:
    return SettingConfig().db_path


def _load_prompt(file_path: str) -> str:
    full_path = os.path.join(appPaths.ASSETS_DIR, file_path)
    # 路径穿越防护：确保解析后路径仍在 ASSETS_DIR 内
    assets_real = os.path.realpath(appPaths.ASSETS_DIR)
    target_real = os.path.realpath(full_path)
    if target_real != assets_real and not target_real.startswith(assets_real + os.sep):
        raise ValueError(f"prompt_file 路径越界: {file_path}")
    with open(full_path, "r", encoding="utf-8") as f:
        return f.read().strip()


def _load_role_templates(config_dir: str) -> List[RoleTemplatePreset]:
    role_templates_dir = os.path.join(config_dir, "role_templates")
    raw_templates = load_json_objects_from_dir(role_templates_dir)
    templates: list[RoleTemplatePreset] = []
    for raw_template in raw_templates:
        template = RoleTemplatePreset.model_validate(raw_template)
        if not template.soul and template.prompt_file:
            template = template.model_copy(update={"soul": _load_prompt(template.prompt_file)})
        templates.append(template)
    return templates


def _load_teams(config_dir: str) -> List[TeamPreset]:
    teams_dir = os.path.join(config_dir, "teams")
    raw_teams = load_json_objects_from_dir(teams_dir)
    return [TeamPreset.model_validate(team) for team in raw_teams]


def _copy_template_if_missing(src_name: str, dest_dir: str, dest_name: str | None = None) -> None:
    resolved_dest_name = dest_name or src_name
    src_path = os.path.join(appPaths.ASSETS_DIR, src_name)
    dest_path = os.path.join(dest_dir, resolved_dest_name)

    if os.path.isfile(dest_path):
        return

    if not os.path.isfile(src_path):
        raise FileNotFoundError(
            f"配置模板不存在: {src_path}\n"
            f"请检查程序安装是否完整。"
        )

    shutil.copy(src_path, dest_path)


def sync_file_if_changed(src_name: str, dest_dir: str, dest_name: str | None = None) -> None:
    """同步文件到目标目录，不存在或内容不一致时更新。"""
    resolved_dest_name = dest_name or src_name
    src_path = os.path.join(appPaths.ASSETS_DIR, src_name)
    dest_path = os.path.join(dest_dir, resolved_dest_name)

    if not os.path.isfile(src_path):
        raise FileNotFoundError(
            f"模板文件不存在: {src_path}\n"
            f"请检查程序安装是否完整。"
        )

    # 不存在则直接复制
    if not os.path.isfile(dest_path):
        shutil.copy(src_path, dest_path)
        return

    # 内容不一致则更新
    with open(src_path, "r", encoding="utf-8") as f:
        src_content = f.read()
    with open(dest_path, "r", encoding="utf-8") as f:
        dest_content = f.read()

    if src_content != dest_content:
        shutil.copy(src_path, dest_path)


def _load_setting(config_dir: str) -> SettingConfig:
    path = os.path.join(config_dir, "setting.json")

    # 自动创建配置目录
    os.makedirs(config_dir, exist_ok=True)

    if not os.path.isfile(path):
        # 从模板复制配置文件
        _copy_template_if_missing("config_template.json", config_dir, "setting.json")

    # 每次启动同步 README 文档（不存在或内容不一致时更新）
    # 测试环境下跳过，避免在测试配置目录生成不必要的文件
    if not _is_running_tests():
        sync_file_if_changed("docs/setting.README.md", config_dir, "setting.README.md")

    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass

    if not isinstance(cfg, dict):
        raise ValueError(f"setting.json 内容必须是对象: {path}")

    # 测试环境下支持通过环境变量强制指定 Mock LLM 端口，解决并发测试时的端口冲突。
    mock_port = os.environ.get("TEAMAGENT_MOCK_LLM_PORT")
    if mock_port and os.environ.get("TEAMAGENT_ENV") == "test":
        for svc in cfg.get("llm_services", []):
            svc_type = str(svc.get("type", "")).lower()
            if svc_type == "anthropic":
                svc["base_url"] = f"http://127.0.0.1:{mock_port}/v1/messages"
            else:
                svc["base_url"] = f"http://127.0.0.1:{mock_port}/v1/chat/completions"

    # 迁移：将旧版默认的 reserve_output_tokens=8192 升级为 16384
    for svc in cfg.get("llm_services", []):
        if svc.get("reserve_output_tokens") == 8192:
            svc["reserve_output_tokens"] = 16384

    setting = SettingConfig.model_validate(cfg)
    apply_secret_environment_overrides(setting)
    return setting


def load_json_objects_from_dir(dir_path: str) -> list[dict[str, Any]]:
    """加载目录下全部 json 文件，按文件名排序返回 json 对象列表。"""
    result: list[dict[str, Any]] = []
    for path in sorted(glob.glob(os.path.join(dir_path, "*.json"))):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError(f"JSON 文件内容必须是对象: {path}")
        result.append(data)
    return result


def get_app_config() -> AppConfig:
    if _cached_app_config is None:
        raise RuntimeError("AppConfig 未初始化，请先调用 configUtil.load(...)")
    return _cached_app_config


def get_language() -> str:
    """获取当前语言设置。"""
    return get_app_config().setting.language


def set_language(lang: str) -> None:
    """修改语言设置并持久化到 setting.json。"""
    update_setting(lambda s: setattr(s, "language", lang))


def is_loaded() -> bool:
    """判断配置是否已加载。"""
    return _cached_app_config is not None


def is_initialized() -> bool:
    """判断系统是否已完成 LLM 服务初始化配置。

    至少有一个已启用的服务时返回 True。
    如果用户未配置任何服务但有内置默认 Key，也返回 True。
    """
    if _cached_app_config is None:
        return False
    setting = _cached_app_config.setting
    if setting.llm_services and any(s.enable for s in setting.llm_services):
        return True
    # 用户未配置但有内置 Key → 已就绪
    builtin = _load_builtin_keys()
    return bool(builtin.get("llm_services"))


def is_demo_mode() -> bool:
    """当前是否启用演示模式。"""
    if _cached_app_config is None:
        return False
    return bool(_cached_app_config.setting.demo_mode.enabled)


def load(config_dir: str = None, preset_dir: str = None, force_reload: bool = False) -> AppConfig:
    """一次性加载所有配置，写入缓存并返回。

    Args:
        preset_dir: 指定 role_templates/teams 的查找目录；为 None 时使用默认 preset/。
    """
    global _cached_app_config, _cached_config_dir, _cached_preset_dir

    resolved_config_dir = _resolve_config_dir(config_dir)
    resolved_preset_dir = os.path.abspath(preset_dir) if preset_dir else _resolve_preset_dir()
    if not force_reload and _cached_app_config is not None and _cached_config_dir == resolved_config_dir:
        return _cached_app_config

    role_templates = _load_role_templates(resolved_preset_dir)
    teams = _load_teams(resolved_preset_dir)
    setting = _load_setting(resolved_config_dir)

    app_config = AppConfig(
        role_templates_preset=role_templates,
        teams_preset=teams,
        setting=setting,
    )
    _cached_app_config = app_config
    _cached_config_dir = resolved_config_dir
    _cached_preset_dir = resolved_preset_dir
    return app_config


def update_setting(mutator: Callable[[SettingConfig], None]) -> None:
    """原子性地修改内存中的 SettingConfig，然后同步写回文件。

    mutator 函数接收当前 SettingConfig，直接就地修改字段值。
    调用完成后自动触发 _save_setting_to_file()。

    使用 threading.Lock 保护读改写全过程，防止并发请求交错丢失更新。
    """
    if _cached_app_config is None:
        raise RuntimeError("AppConfig 未初始化，请先调用 configUtil.load(...)")
    with _setting_lock:
        mutator(_cached_app_config.setting)
        _save_setting_to_file()


def _save_setting_to_file() -> None:
    """将当前内存中的 SettingConfig 序列化后写回 setting.json。

    写入策略：先写临时文件再 os.replace，确保原子性。
    采用 JSON 合并写回：读取原文件 → 更新 llm_services / default_llm_server → 写回，
    保留原文件中的 _comment 等非模型字段。
    使用 exclude_unset=True 仅写入显式设置过的字段，保持配置文件精简。
    """
    path = os.path.join(_cached_config_dir, "setting.json")

    # 读取原始 JSON（保留 _comment 等非模型字段）
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    setting = _cached_app_config.setting
    raw["llm_services"] = [
        s.model_dump(exclude_unset=True, mode="json") for s in setting.llm_services
    ]
    raw["default_llm_server"] = setting.default_llm_server
    raw["language"] = setting.language
    raw["development_mode"] = setting.development_mode
    raw["auth"] = setting.auth.model_dump(exclude_unset=True, mode="json")
    ghost_raw = setting.ghost.model_dump(exclude_unset=True, mode="json")
    # Environment-injected secrets must remain process-only. Preserve the
    # existing file value instead of accidentally persisting an env secret when
    # an unrelated setting is updated through the API.
    existing_ghost = raw.get("ghost") if isinstance(raw.get("ghost"), dict) else {}
    if os.environ.get("GHOST_API_URL"):
        ghost_raw["api_url"] = existing_ghost.get("api_url", "")
    if os.environ.get("GHOST_ADMIN_API_KEY"):
        ghost_raw["admin_api_key"] = existing_ghost.get("admin_api_key", "")
    if os.environ.get("GHOST_CONTENT_API_KEY"):
        ghost_raw["content_api_key"] = existing_ghost.get("content_api_key", "")
    raw["ghost"] = ghost_raw
    raw["driver_fallback"] = setting.driver_fallback.model_dump(exclude_unset=True, mode="json")

    # 原子写入：先写临时文件再 os.replace。失败时清理残留 .tmp 文件。
    # 设置 0o600 权限保护含 api_key/token 的配置文件，防止 world-readable。
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(raw, f, indent=2, ensure_ascii=False)
            f.write("\n")
        try:
            os.chmod(tmp_path, 0o600)
        except OSError:
            pass  # 某些文件系统（如 FAT）不支持权限
        os.replace(tmp_path, path)
    except Exception:
        # 序列化或写入失败时清理残留临时文件，避免累积 .tmp 残片
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        raise
