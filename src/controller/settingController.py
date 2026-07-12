import json
import logging
import time

from pydantic import BaseModel, ValidationError

from constants import LlmServiceType
from controller.baseController import BaseHandler
from service import ghostService, llmService, schedulerService
from util import assertUtil, configUtil, safeHttpUtil
from util.configTypes import GhostConfig, LlmServiceConfig

logger = logging.getLogger(__name__)

# LiteLLM custom_llm_provider 映射（与 llmService 保持一致）
_TYPE_TO_PROVIDER = {
    LlmServiceType.OPENAI_COMPATIBLE: "openai",
    LlmServiceType.ANTHROPIC: "anthropic",
    LlmServiceType.GOOGLE: "gemini",
    LlmServiceType.DEEPSEEK: "deepseek",
}

def _assert_safe_service_url(url: str, *, field_name: str = "base_url") -> None:
    try:
        ghostService.assert_safe_http_url(url, field_name=field_name)
    except ValueError as exc:
        raise assertUtil.MakeSureException(str(exc), error_code="unsafe_url") from exc


def _assert_safe_llm_url(base_url: str) -> None:
    _assert_safe_service_url(base_url, field_name="base_url")


class TestLlmServiceRequest(BaseModel):
    """可用性测试请求，通过 mode 字段区分已保存服务和临时配置。"""
    mode: str  # "saved" | "temp"
    index: int | None = None
    base_url: str | None = None
    api_key: str | None = None
    type: str | None = None
    model: str | None = None
    extra_headers: dict[str, str] | None = None
    provider_params: dict[str, object] | None = None


def _get_setting():
    return configUtil.get_app_config().setting


def _serialize_llm_service(service: LlmServiceConfig) -> dict:
    """序列化 LLM 服务配置。

    安全策略：api_key 始终不返回明文（仅返回 has_api_key 布尔），
    extra_headers 脱敏为 ***。demo 模式额外隐藏 base_url。
    """
    item = service.model_dump(exclude_unset=True, mode="json")
    item.setdefault("provider_params", {})
    item["has_api_key"] = bool(service.api_key)
    # 始终脱敏 api_key：前端仅需 has_api_key 布尔值
    item["api_key"] = ""
    # 脱敏 extra_headers 中的凭据
    if item.get("extra_headers"):
        item["extra_headers"] = {k: "***" for k in item["extra_headers"]}
    demo_mode = configUtil.get_app_config().setting.demo_mode
    if demo_mode.hide_sensitive:
        item["base_url"] = ""
        item["extra_headers"] = {}
    return item


def _validate_index(index_str: str) -> int:
    """将路径参数转为合法的数组下标。"""
    index = int(index_str)
    services = _get_setting().llm_services
    assertUtil.assertTrue(
        0 <= index < len(services),
        error_message=f"服务序号 {index} 越界，当前共 {len(services)} 个服务",
        error_code="index_out_of_range",
    )
    return index


class LlmServiceListHandler(BaseHandler):
    """GET /config/llm_services/list.json

    安全策略：
    - 用户自定义的 Key 始终不返回明文（仅 has_api_key 布尔）
    - 内置默认 Key 对用户完全不可见（标记为 builtin，Key 为空）
    - 用户可添加自己的 Key 覆盖内置服务
    """

    async def get(self) -> None:
        setting = _get_setting()
        user_services = [_serialize_llm_service(service) for service in setting.llm_services]

        # 检查用户配置中是否有已启用的服务
        has_enabled_user_service = any(s.enable for s in setting.llm_services)

        # 如果用户无可用服务（未配置或全部禁用），附加内置服务
        if not has_enabled_user_service:
            builtin_services = configUtil.get_builtin_llm_services()
            for svc in builtin_services:
                item = dict(svc)
                item["has_api_key"] = True
                item["api_key"] = ""  # 内置 Key 不返回明文
                item["is_builtin"] = True
                item.setdefault("provider_params", {})
                user_services.append(item)

            builtin_default = configUtil.get_builtin_default_llm_server()
            self.return_json({
                "llm_services": user_services,
                "default_llm_server": builtin_default or setting.default_llm_server or "",
            })
            return

        # 标记用户自定义服务
        for svc in user_services:
            svc["is_builtin"] = False

        self.return_json({
            "llm_services": user_services,
            "default_llm_server": setting.default_llm_server,
        })


class LlmServiceCreateHandler(BaseHandler):
    """POST /config/llm_services/create.json"""

    async def post(self) -> None:
        self._assert_admin()
        try:
            new_service = self.parse_request(LlmServiceConfig)
        except ValidationError as e:
            self.return_with_error(
                error_code="validation_error",
                error_desc=str(e),
            )
            return

        setting = _get_setting()

        # 校验名称不重复
        existing_names = {s.name for s in setting.llm_services}
        assertUtil.assertTrue(
            new_service.name not in existing_names,
            error_message=f"服务名称 '{new_service.name}' 已存在",
            error_code="name_duplicate",
        )

        _assert_safe_llm_url(new_service.base_url)

        def mutator(s):
            s.llm_services.append(new_service)

        configUtil.update_setting(mutator)
        llmService.reset_request_gates_for_testing()
        self.return_json({"status": "ok", "index": len(setting.llm_services) - 1})


class LlmServiceModifyHandler(BaseHandler):
    """POST /config/llm_services/{index}/modify.json"""

    async def post(self, index_str: str) -> None:
        self._assert_admin()
        index = _validate_index(index_str)
        setting = _get_setting()
        service = setting.llm_services[index]

        body = json.loads(self.request.body)
        known_fields = set(LlmServiceConfig.model_fields.keys()) - {"name"}
        updates = {k: v for k, v in body.items() if k in known_fields}

        assertUtil.assertTrue(
            len(updates) > 0,
            error_message="未提供任何可修改的字段",
            error_code="no_update_fields",
        )

        # 不能禁用当前默认服务
        if "enable" in updates and updates["enable"] is False:
            assertUtil.assertTrue(
                service.name != setting.default_llm_server,
                error_message="不能禁用当前默认服务，请先切换默认服务",
                error_code="cannot_disable_default",
            )

        if "base_url" in updates:
            url = updates["base_url"]
            assertUtil.assertTrue(isinstance(url, str), error_message="base_url 必须是字符串", error_code="invalid_base_url")
            _assert_safe_llm_url(url)

        # dict 合并重建，Pydantic 自动校验
        current = service.model_dump(exclude_unset=True)
        current.update(updates)
        try:
            new_service = LlmServiceConfig(**current)
        except ValidationError as e:
            self.return_with_error(
                error_code="validation_error",
                error_desc=str(e),
            )
            return

        def mutator(s):
            s.llm_services[index] = new_service

        configUtil.update_setting(mutator)
        llmService.reset_request_gates_for_testing()

        if not configUtil.is_initialized():
            schedulerService.stop_schedule("无可用的大模型服务")

        self.return_json({"status": "ok"})


class LlmServiceDeleteHandler(BaseHandler):
    """POST /config/llm_services/{index}/delete.json"""

    async def post(self, index_str: str) -> None:
        self._assert_admin()
        index = _validate_index(index_str)
        setting = _get_setting()
        service = setting.llm_services[index]

        assertUtil.assertTrue(
            service.name != setting.default_llm_server,
            error_message="不能删除当前默认服务，请先切换默认服务",
            error_code="cannot_delete_default",
        )

        def mutator(s):
            s.llm_services.pop(index)

        configUtil.update_setting(mutator)
        llmService.reset_request_gates_for_testing()

        # 删除服务后检查：若无可用 LLM 服务，阻塞调度
        if not configUtil.is_initialized():
            schedulerService.stop_schedule("无可用的大模型服务")

        self.return_json({"status": "ok", "deleted_name": service.name})


class LlmServiceSetDefaultHandler(BaseHandler):
    """POST /config/llm_services/{index}/set_default.json"""

    async def post(self, index_str: str) -> None:
        self._assert_admin()
        index = _validate_index(index_str)
        setting = _get_setting()
        service = setting.llm_services[index]

        assertUtil.assertTrue(
            service.enable,
            error_message=f"服务 '{service.name}' 已禁用，无法设为默认",
            error_code="cannot_default_disabled",
        )

        def mutator(s):
            s.default_llm_server = service.name

        configUtil.update_setting(mutator)
        self.return_json({"status": "ok", "default_llm_server": service.name})


class LlmServiceTestHandler(BaseHandler):
    """POST /config/llm_services/test.json"""

    async def post(self) -> None:
        self._assert_admin()
        request = self.parse_request(TestLlmServiceRequest)

        assertUtil.assertTrue(
            request.mode in ("saved", "temp"),
            error_message="mode 必须为 'saved' 或 'temp'",
            error_code="invalid_mode",
        )

        if request.mode == "saved":
            assertUtil.assertNotNull(
                request.index,
                error_message="mode='saved' 时必须提供 index",
                error_code="missing_index",
            )
            setting = _get_setting()
            assertUtil.assertTrue(
                0 <= request.index < len(setting.llm_services),
                error_message=f"服务序号 {request.index} 越界",
                error_code="index_out_of_range",
            )
            config = setting.llm_services[request.index]
        else:
            assertUtil.assertNotNull(request.base_url, error_message="mode='temp' 时必须提供 base_url", error_code="missing_field")
            assertUtil.assertNotNull(request.api_key, error_message="mode='temp' 时必须提供 api_key", error_code="missing_field")
            assertUtil.assertNotNull(request.type, error_message="mode='temp' 时必须提供 type", error_code="missing_field")
            assertUtil.assertNotNull(request.model, error_message="mode='temp' 时必须提供 model", error_code="missing_field")

            # SSRF 防护：校验 base_url 不指向内网/回环/元数据端点
            _assert_safe_llm_url(request.base_url)

            config = LlmServiceConfig(
                name="__test__",
                base_url=request.base_url,
                api_key=request.api_key,
                type=LlmServiceType(request.type),
                model=request.model,
                extra_headers=request.extra_headers or {},
                provider_params=request.provider_params or {},
            )

        # 已保存与临时配置走同一 SSRF 校验，避免旧配置绕过测试接口。
        _assert_safe_llm_url(config.base_url)

        # 执行可用性测试
        try:
            result = await _test_llm_service(config)
            self.return_json({
                "status": "ok",
                "message": "连接成功",
                "detail": result,
            })
        except Exception as e:
            logger.warning(f"LLM 可用性测试失败: {e}", exc_info=True)
            # 不回显原始上游异常（可能含内网地址/端口/鉴权细节），返回统一下游错误码
            self.return_json({
                "status": "error",
                "message": "LLM 服务连接失败，请检查配置",
                "detail": {
                    "error_type": type(e).__name__,
                },
            })


async def _test_llm_service(config: LlmServiceConfig) -> dict:
    """Send a minimal provider probe through the shared SSRF-safe HTTP client.

    The normal LiteLLM path remains unchanged for Agent execution. Configuration
    testing intentionally uses this small direct request so DNS pinning and manual
    redirect validation cannot be bypassed inside a third-party HTTP stack.
    """
    base_url = config.base_url.rstrip("/")
    headers = {str(k): str(v) for k, v in (config.extra_headers or {}).items()}
    timeout = 30.0

    if config.type == LlmServiceType.ANTHROPIC:
        endpoint = base_url if base_url.endswith("/messages") else f"{base_url}/messages"
        headers.update({
            "x-api-key": config.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        })
        payload = {
            "model": config.model, "max_tokens": 8,
            "messages": [{"role": "user", "content": "Reply OK"}],
        }
    elif config.type == LlmServiceType.GOOGLE:
        from urllib.parse import quote
        model = quote(config.model, safe="")
        root = base_url[:-3] if base_url.endswith("/v1") else base_url
        endpoint = f"{root}/v1beta/models/{model}:generateContent?key={quote(config.api_key, safe='')}"
        headers.setdefault("content-type", "application/json")
        payload = {"contents": [{"parts": [{"text": "Reply OK"}]}], "generationConfig": {"maxOutputTokens": 8}}
    else:
        endpoint = base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"
        headers.update({
            "Authorization": f"Bearer {config.api_key}",
            "content-type": "application/json",
        })
        payload = {
            "model": config.model, "messages": [{"role": "user", "content": "Reply OK"}],
            "max_tokens": 8, "stream": False,
        }

    start_time = time.monotonic()
    response = await safeHttpUtil.request(
        "POST", endpoint, headers=headers, json_body=payload, timeout=timeout,
        field_name="base_url",
    )
    duration_ms = int((time.monotonic() - start_time) * 1000)
    if response.status < 200 or response.status >= 300:
        raise RuntimeError(f"upstream returned HTTP {response.status}")
    data = response.json() if response.body else {}
    return {
        "model": config.model,
        "duration_ms": duration_ms,
        "usage": data.get("usage") or data.get("usageMetadata"),
        "test_mode": "ssrf_safe_provider_probe",
    }


_SUPPORTED_LANGUAGES = {"zh-CN", "en"}


class LanguageHandler(BaseHandler):
    """POST /config/language.json — 设置界面语言偏好。"""

    async def post(self) -> None:
        self._assert_admin()
        body = self.parse_request_dict()
        lang = body.get("language", "")
        assertUtil.assertTrue(
            lang in _SUPPORTED_LANGUAGES,
            error_message=f"不支持的语言：{lang!r}，可选值：{sorted(_SUPPORTED_LANGUAGES)}",
            error_code="unsupported_language",
        )
        configUtil.set_language(lang)
        self.return_json({"status": "ok", "language": lang})


class SkillListHandler(BaseHandler):
    """GET /config/skills/list.json — 返回系统可用的 Skill 列表。"""

    async def get(self) -> None:
        import service.skillService as skillService
        skills = skillService.get_all_skills()
        self.return_json({
            "skills": [
                {
                    "name": s.name,
                    "description": s.description,
                    "is_builtin": s.is_builtin,
                    "files": s.files
                }
                for s in skills
            ],
        })


class SkillImportHandler(BaseHandler):
    """POST /config/skills/import.json — 上传 zip 导入 Skill。"""

    async def post(self) -> None:
        self._assert_admin()
        from pydantic import ValidationError
        from service import skillImportService

        if self.request.headers.get("Content-Type", "").startswith("multipart/form-data"):
            force = self.get_argument("force", "false").lower() == "true"
            file_info = self.request.files.get("file")
            if not file_info:
                self.return_with_error(error_code="missing_file", error_desc="请上传 zip 文件")
                return
            zip_bytes = file_info[0]["body"]
        else:
            try:
                body = self.parse_request(dict)
            except ValidationError:
                self.return_with_error(error_code="invalid_body", error_desc="请求体必须是 JSON")
                return
            zip_bytes = body.get("zip_bytes")
            force = bool(body.get("force", False))
            if not zip_bytes or not isinstance(zip_bytes, bytes):
                self.return_with_error(error_code="missing_zip", error_desc="缺少 zip_bytes")
                return

        try:
            result = await skillImportService.import_skill_from_zip(zip_bytes, force=force)
            self.return_json(result)
        except skillImportService.SkillImportError as e:
            self.return_with_error(error_code="skill_import_failed", error_desc=str(e))


class SkillDeleteHandler(BaseHandler):
    """POST /config/skills/{name}/delete.json — 删除用户导入的 Skill。"""

    async def post(self, name: str) -> None:
        self._assert_admin()
        from service import skillImportService

        try:
            result = await skillImportService.delete_user_skill(name)
            self.return_json(result)
        except skillImportService.SkillImportError as e:
            self.return_with_error(error_code="skill_delete_failed", error_desc=str(e))


class ToolListHandler(BaseHandler):
    """GET /config/tools/list.json — 返回系统可用的 Tool 列表。"""

    async def get(self) -> None:
        from service.agentService.toolRegistry import CATEGORY_CONFIG
        tools = []
        for name, category in CATEGORY_CONFIG.items():
            if category.name not in ("ADMIN", "BASIC"):
                tools.append({"name": name, "category": category.name})
        
        # Add predefined categories
        tools.extend([
            {"name": "Category:Read", "category": "CATEGORY"},
            {"name": "Category:Write", "category": "CATEGORY"},
            {"name": "Category:Execute", "category": "CATEGORY"},
        ])
        
        self.return_json({"tools": tools})


def _apply_ghost_config_patch(ghost: GhostConfig, body: dict[str, object]) -> None:
    """Apply a Ghost config patch without exposing or accidentally clearing secrets."""
    if "enabled" in body:
        ghost.enabled = bool(body["enabled"])
    if "api_url" in body:
        ghost.api_url = str(body["api_url"]).strip()
    if bool(body.get("clear_admin_api_key")):
        ghost.admin_api_key = ""
    elif str(body.get("admin_api_key", "")).strip():
        ghost.admin_api_key = str(body["admin_api_key"]).strip()
    if bool(body.get("clear_content_api_key")):
        ghost.content_api_key = ""
    elif str(body.get("content_api_key", "")).strip():
        ghost.content_api_key = str(body["content_api_key"]).strip()
    if "auto_publish" in body:
        ghost.auto_publish = bool(body["auto_publish"])
    if "publish_status" in body:
        status = str(body["publish_status"]).strip().lower()
        if status not in {"published", "draft"}:
            raise assertUtil.TogoException("publish_status 必须为 published 或 draft")
        ghost.publish_status = status


class GhostConfigHandler(BaseHandler):
    """GET/POST /config/ghost.json — Ghost CMS 博客发布配置。"""

    async def get(self) -> None:
        ghost = _get_setting().ghost
        # 密钥永不返回明文。空字符串用于保持前端表单兼容。
        self.return_json({
            "enabled": ghost.enabled,
            "api_url": ghost.api_url,
            "admin_api_key": "",
            "content_api_key": "",
            "auto_publish": ghost.auto_publish,
            "publish_status": ghost.publish_status,
            "has_admin_key": bool(ghost.admin_api_key),
            "has_content_key": bool(ghost.content_api_key),
            "has_key": bool(ghost.admin_api_key),  # 兼容旧前端
            "is_builtin": False,
        })

    async def post(self) -> None:
        self._assert_admin()
        body = self.parse_request_dict()
        if "api_url" in body:
            api_url = str(body["api_url"]).strip()
            if api_url:
                _assert_safe_service_url(api_url, field_name="Ghost API URL")

        # 空 key 表示保留；只有显式 clear_* 才清空保存值。
        configUtil.update_setting(lambda setting: _apply_ghost_config_patch(setting.ghost, body))
        ghost = _get_setting().ghost
        self.return_json({
            "success": True,
            "has_admin_key": bool(ghost.admin_api_key),
            "has_content_key": bool(ghost.content_api_key),
        })


class GhostTestHandler(BaseHandler):
    """POST /config/ghost/test.json — 测试 Ghost CMS 连接。"""

    async def post(self) -> None:
        self._assert_admin()
        body = self.parse_request_dict()
        api_url = body.get("api_url", "").strip()
        admin_api_key = body.get("admin_api_key", "").strip()

        # 如果未传入，使用已保存的配置
        if not api_url or not admin_api_key:
            ghost = _get_setting().ghost
            api_url = api_url or ghost.api_url
            admin_api_key = admin_api_key or ghost.admin_api_key

        _assert_safe_service_url(api_url, field_name="Ghost API URL")
        result = await ghostService.test_ghost_connection(api_url, admin_api_key)
        self.return_json(result)
