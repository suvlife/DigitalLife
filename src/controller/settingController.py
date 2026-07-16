import json
import logging
import time

from pydantic import BaseModel, ValidationError

from constants import LlmServiceType, ScheduleState
from controller.baseController import BaseHandler, format_validation_error
from service import ghostService, llmService, schedulerService
from util import assertUtil, configUtil, safeHttpUtil
from util.configTypes import GhostConfig, LlmServiceConfig, SearchProviderConfig, SearchToolsConfig

logger = logging.getLogger(__name__)

# LiteLLM custom_llm_provider 映射（与 llmService 保持一致）
_TYPE_TO_PROVIDER = {
    LlmServiceType.OPENAI_COMPATIBLE: "openai",
    LlmServiceType.ANTHROPIC: "anthropic",
    LlmServiceType.GOOGLE: "gemini",
    LlmServiceType.DEEPSEEK: "deepseek",
}

def _assert_safe_service_url(url: str, *, field_name: str = "base_url", allow_private: bool = False) -> None:
    try:
        ghostService.assert_safe_http_url(url, field_name=field_name, allow_private=allow_private)
    except safeHttpUtil.UnsafeUrlError as exc:
        logger.warning("SSRF check failed for %s=%s: %s", field_name, url, exc)
        raise assertUtil.MakeSureException(
            f"URL 安全检查失败（{field_name}={url}）: {exc}",
            error_code="unsafe_url",
        ) from exc
    except ValueError as exc:
        logger.warning("URL validation failed for %s=%s: %s", field_name, url, exc)
        raise assertUtil.MakeSureException(str(exc), error_code="unsafe_url") from exc


def _assert_safe_llm_url(base_url: str) -> None:
    """LLM base_url 校验：允许私有/回环地址，因为用户可能配置本地 LLM（如 Ollama）。"""
    _assert_safe_service_url(base_url, field_name="base_url", allow_private=True)


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


def _serialize_llm_service(service: LlmServiceConfig, *, is_admin: bool = True) -> dict:
    """序列化 LLM 服务配置。

    安全策略：api_key 始终不返回明文（仅返回 has_api_key 布尔），
    extra_headers 脱敏为 ***。demo 模式或非管理员额外隐藏 base_url（审计 M6）。
    """
    item = service.model_dump(exclude_unset=True, mode="json")
    item.setdefault("provider_params", {})
    item["has_api_key"] = bool(service.api_key) or bool(service.api_keys)
    # 始终脱敏 api_key：前端仅需 has_api_key 布尔值
    item["api_key"] = ""
    # 脱敏 extra_headers 中的凭据
    if item.get("extra_headers"):
        item["extra_headers"] = {k: "***" for k in item["extra_headers"]}
    demo_mode = configUtil.get_app_config().setting.demo_mode
    # M6：base_url 属基础设施敏感信息，非管理员或 demo 隐私模式下屏蔽
    if demo_mode.hide_sensitive or not is_admin:
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
        is_admin = self._is_admin()
        # 为每个用户自定义服务标注其在 setting.llm_services 中的真实 index，
        # 前端据此调用 modify/test/delete 接口，避免与内置服务混排后越界。
        user_services = []
        for i, service in enumerate(setting.llm_services):
            item = _serialize_llm_service(service, is_admin=is_admin)
            item["index"] = i
            user_services.append(item)

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
                item["index"] = -1  # 内置服务不可通过 index 修改/删除
                item.setdefault("provider_params", {})
                # M6：非管理员不暴露内置服务的 base_url
                if not is_admin:
                    item["base_url"] = ""
                    item["extra_headers"] = {}
                user_services.append(item)

            builtin_default = configUtil.get_builtin_default_llm_server()
            self.return_json({
                "llm_services": user_services,
                "default_llm_server": builtin_default or setting.default_llm_server or "",
                "fallback_llm_servers": setting.fallback_llm_servers,
            })
            return

        # 标记用户自定义服务
        for svc in user_services:
            svc["is_builtin"] = False

        self.return_json({
            "llm_services": user_services,
            "default_llm_server": setting.default_llm_server,
            "fallback_llm_servers": setting.fallback_llm_servers,
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
                error_desc=format_validation_error(e),
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

        # 添加服务后如果系统已就绪但调度器未运行，自动启动调度
        if configUtil.is_initialized() and schedulerService.get_schedule_state() != ScheduleState.RUNNING:
            await schedulerService.start_schedule()

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
                error_desc=format_validation_error(e),
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

        # 设置默认服务后如果系统已就绪但调度器未运行，自动启动调度
        if configUtil.is_initialized() and schedulerService.get_schedule_state() != ScheduleState.RUNNING:
            await schedulerService.start_schedule()

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
            if request.index == -1:
                # index=-1 表示测试内置服务：从 builtin_keys 中查找
                builtin_services = configUtil.get_builtin_llm_services()
                assertUtil.assertTrue(
                    len(builtin_services) > 0,
                    error_message="无内置服务可测试",
                    error_code="no_builtin_service",
                )
                # 取第一个启用的内置服务
                svc = next((s for s in builtin_services if s.get("enable")), builtin_services[0])
                config = LlmServiceConfig(
                    name=svc.get("name", "builtin"),
                    enable=True,
                    base_url=svc.get("base_url", ""),
                    api_key=svc.get("api_key", ""),
                    api_keys=list(svc.get("api_keys", []) or []),
                    type=LlmServiceType(svc.get("type", "openai-compatible")),
                    model=svc.get("model", ""),
                )
            else:
                assertUtil.assertTrue(
                    0 <= request.index < len(setting.llm_services),
                    error_message=f"服务序号 {request.index} 越界，当前共 {len(setting.llm_services)} 个服务",
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

        # PyInstaller 打包后可能缺少系统 CA 证书，允许跳过 SSL 验证
        skip_ssl = bool(request.provider_params.get("skip_ssl_verify")) if request.provider_params else False

        # 执行可用性测试
        try:
            result = await _test_llm_service(config, skip_ssl_verify=skip_ssl)
            self.return_json({
                "status": "ok",
                "message": "连接成功",
                "detail": result,
            })
        except Exception as e:
            logger.warning(f"LLM 可用性测试失败: {e}", exc_info=True)
            # 返回分类后的错误信息，帮助用户定位问题（SSL/DNS/认证/网络等）
            error_msg = _classify_llm_test_error(e)
            self.return_json({
                "status": "error",
                "message": error_msg,
                "detail": {
                    "error_type": type(e).__name__,
                },
            })


def _classify_llm_test_error(e: Exception) -> str:
    """将 LLM 测试异常分类为用户可理解的错误信息。"""
    err_str = str(e).lower()
    err_type = type(e).__name__

    # SSL 证书相关
    if "ssl" in err_str or "certificate" in err_str or "cert" in err_str:
        return "SSL 证书验证失败，请在 provider_params 中设置 skip_ssl_verify=true，或检查系统 CA 证书"

    # DNS 解析相关
    if "resolve" in err_str or "dns" in err_str or "gaierror" in err_type.lower() or "hostname" in err_str:
        return f"域名解析失败，请检查 base_url 是否正确: {e}"

    # 连接超时/拒绝
    if "timeout" in err_str or "timed out" in err_str:
        return "连接超时，请检查网络是否可达或增加超时时间"
    if "connection refused" in err_str or "connectionerror" in err_type.lower():
        return "连接被拒绝，请检查服务地址和端口是否正确"
    if "connection" in err_str and "reset" in err_str:
        return "连接被重置，可能是网络不稳定或服务端拒绝"

    # 认证相关
    if "401" in err_str or "unauthorized" in err_str or "authentication" in err_str or "invalid api key" in err_str:
        return "认证失败（HTTP 401），请检查 API Key 是否正确"

    # 限流
    if "429" in err_str or "rate limit" in err_str:
        return "请求被限流（HTTP 429），请稍后重试或降低请求频率"

    # 模型相关
    if "404" in err_str or "not found" in err_str or "model" in err_str:
        return "模型不存在或路径错误（HTTP 404），请检查 model 名称和 base_url 路径"

    # SSRF 拦截
    if "unsafe_url" in err_str or "non-public" in err_str or "ssrf" in err_str:
        return f"URL 安全检查失败: {e}"

    # 通用网络错误
    if "network" in err_str or "unreachable" in err_str:
        return f"网络不可达: {e}"

    # HTTP 错误状态码
    if "http" in err_str and any(c.isdigit() for c in err_str):
        return f"服务返回错误: {e}"

    return f"LLM 服务连接失败: {e}"


async def _test_llm_service(config: LlmServiceConfig, *, skip_ssl_verify: bool = False) -> dict:
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
        # 审计 M15：用 x-goog-api-key 请求头承载密钥，而非放入 URL query，
        # 避免密钥进入 aiohttp 内部日志 / 中间层 / 跨域重定向 query。
        endpoint = f"{root}/v1beta/models/{model}:generateContent"
        headers.update({
            "x-goog-api-key": config.api_key,
            "content-type": "application/json",
        })
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
        field_name="base_url", allow_private=True,
        ssl=False if skip_ssl_verify else None,
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
    if "skip_ssl_verify" in body:
        ghost.skip_ssl_verify = bool(body["skip_ssl_verify"])


class GhostConfigHandler(BaseHandler):
    """GET/POST /config/ghost.json — Ghost CMS 博客发布配置。"""

    async def get(self) -> None:
        ghost = _get_setting().ghost
        # 密钥永不返回明文。空字符串用于保持前端表单兼容。
        # 审计 M6：api_url 属基础设施敏感信息，非管理员脱敏为空串。
        api_url = ghost.api_url if self._is_admin() else ""
        self.return_json({
            "enabled": ghost.enabled,
            "api_url": api_url,
            "admin_api_key": "",
            "content_api_key": "",
            "auto_publish": ghost.auto_publish,
            "publish_status": ghost.publish_status,
            "has_admin_key": bool(ghost.admin_api_key),
            "has_content_key": bool(ghost.content_api_key),
            "has_key": bool(ghost.admin_api_key),  # 兼容旧前端
            "skip_ssl_verify": ghost.skip_ssl_verify,
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
        skip_ssl_verify = bool(body.get("skip_ssl_verify", _get_setting().ghost.skip_ssl_verify))
        result = await ghostService.test_ghost_connection(api_url, admin_api_key, skip_ssl_verify=skip_ssl_verify)
        self.return_json(result)


# ---------------------------------------------------------------------------
# 搜索工具配置（#5）：多引擎 + 多 key，后台增删改查；key 返回时脱敏。
# ---------------------------------------------------------------------------

def _mask_key(key: str) -> str:
    """脱敏单个 api_key，仅保留尾部少量字符用于识别。"""
    key = (key or "").strip()
    if not key:
        return ""
    if len(key) <= 4:
        return "****"
    return "****" + key[-4:]


def _serialize_search_provider(provider: SearchProviderConfig) -> dict:
    """序列化搜索引擎配置，api_keys 一律脱敏，仅返回掩码与数量。"""
    return {
        "provider": provider.provider,
        "enable": provider.enable,
        "api_keys": [_mask_key(k) for k in provider.api_keys],
        "api_keys_count": len(provider.api_keys),
        "has_api_key": bool(provider.api_keys),
    }


def _validate_search_index(index_str: str) -> int:
    """将路径参数转为合法的 providers 数组下标。"""
    index = int(index_str)
    providers = _get_setting().search.providers
    assertUtil.assertTrue(
        0 <= index < len(providers),
        error_message=f"搜索引擎序号 {index} 越界，当前共 {len(providers)} 个",
        error_code="index_out_of_range",
    )
    return index


class SearchConfigHandler(BaseHandler):
    """GET /config/search.json — 返回搜索工具配置（key 脱敏）。"""

    async def get(self) -> None:
        search = _get_setting().search
        self.return_json({
            "enabled": search.enabled,
            "max_content_length": search.max_content_length,
            "max_fetch_bytes": search.max_fetch_bytes,
            "providers": [_serialize_search_provider(p) for p in search.providers],
        })


class SearchSettingsHandler(BaseHandler):
    """POST /config/search/settings.json — 更新搜索全局开关与抓取上限。"""

    async def post(self) -> None:
        self._assert_admin()
        body = self.parse_request_dict()

        # 先在副本上构建并校验，避免校验失败时污染内存中的实时配置。
        data = _get_setting().search.model_dump()
        if "enabled" in body:
            data["enabled"] = bool(body["enabled"])
        for int_field in ("max_content_length", "max_fetch_bytes"):
            if int_field in body:
                try:
                    data[int_field] = int(body[int_field])
                except (TypeError, ValueError):
                    self.return_with_error(
                        error_code="invalid_argument",
                        error_desc=f"{int_field} 必须是整数",
                    )
                    return

        try:
            new_search = SearchToolsConfig(**data)
        except ValidationError as e:
            self.return_with_error(error_code="validation_error", error_desc=format_validation_error(e))
            return

        def mutator(setting):
            setting.search = new_search

        configUtil.update_setting(mutator)
        self.return_success()


class SearchProviderCreateHandler(BaseHandler):
    """POST /config/search/providers/create.json — 新增一个搜索引擎。"""

    async def post(self) -> None:
        self._assert_admin()
        body = self.parse_request_dict()
        try:
            new_provider = SearchProviderConfig(
                provider=str(body.get("provider", "")),
                api_keys=[str(k) for k in (body.get("api_keys") or [])],
                enable=bool(body.get("enable", True)),
            )
        except ValidationError as e:
            self.return_with_error(error_code="validation_error", error_desc=format_validation_error(e))
            return

        assertUtil.assertTrue(
            bool(new_provider.provider),
            error_message="provider 不能为空",
            error_code="missing_provider",
        )
        setting = _get_setting()
        existing = {p.provider for p in setting.search.providers}
        assertUtil.assertTrue(
            new_provider.provider not in existing,
            error_message=f"搜索引擎 '{new_provider.provider}' 已存在，请改用修改接口",
            error_code="provider_duplicate",
        )

        def mutator(s):
            s.search.providers.append(new_provider)

        configUtil.update_setting(mutator)
        self.return_success(index=len(setting.search.providers) - 1)


class SearchProviderModifyHandler(BaseHandler):
    """POST /config/search/providers/{index}/modify.json — 修改搜索引擎。

    api_keys 仅在请求显式提供时才覆盖（GET 返回的是掩码值，避免误清空）；
    可用 clear_api_keys=true 清空全部 key。
    """

    async def post(self, index_str: str) -> None:
        self._assert_admin()
        index = _validate_search_index(index_str)
        setting = _get_setting()
        current = setting.search.providers[index]

        provider_name = current.provider
        enable = current.enable
        api_keys = list(current.api_keys)

        body = self.parse_request_dict()
        if "provider" in body:
            provider_name = str(body["provider"])
        if "enable" in body:
            enable = bool(body["enable"])
        if bool(body.get("clear_api_keys")):
            api_keys = []
        elif "api_keys" in body and isinstance(body["api_keys"], list):
            api_keys = [str(k) for k in body["api_keys"]]

        try:
            new_provider = SearchProviderConfig(
                provider=provider_name, api_keys=api_keys, enable=enable,
            )
        except ValidationError as e:
            self.return_with_error(error_code="validation_error", error_desc=format_validation_error(e))
            return

        assertUtil.assertTrue(
            bool(new_provider.provider),
            error_message="provider 不能为空",
            error_code="missing_provider",
        )
        # 改名后不得与其他引擎重名
        rename_conflict = any(
            i != index and p.provider == new_provider.provider
            for i, p in enumerate(setting.search.providers)
        )
        assertUtil.assertFalse(
            rename_conflict,
            error_message=f"搜索引擎 '{new_provider.provider}' 已存在",
            error_code="provider_duplicate",
        )

        def mutator(s):
            s.search.providers[index] = new_provider

        configUtil.update_setting(mutator)
        self.return_success()


class SearchProviderDeleteHandler(BaseHandler):
    """POST /config/search/providers/{index}/delete.json — 删除搜索引擎。"""

    async def post(self, index_str: str) -> None:
        self._assert_admin()
        index = _validate_search_index(index_str)
        setting = _get_setting()
        removed = setting.search.providers[index].provider

        def mutator(s):
            s.search.providers.pop(index)

        configUtil.update_setting(mutator)
        self.return_success(deleted_provider=removed)


# ---------------------------------------------------------------------------
# LLM 兜底链（#3）：设置 default_llm_server 不可用时按顺序切换的候选服务名列表。
# ---------------------------------------------------------------------------

class LlmFallbackHandler(BaseHandler):
    """GET/POST /config/llm_services/fallback.json — 读取 / 设置 LLM 兜底链。"""

    async def get(self) -> None:
        setting = _get_setting()
        self.return_json({
            "default_llm_server": setting.default_llm_server,
            "fallback_llm_servers": setting.fallback_llm_servers,
        })

    async def post(self) -> None:
        self._assert_admin()
        body = self.parse_request_dict()
        raw = body.get("fallback_llm_servers")
        assertUtil.assertTrue(
            isinstance(raw, list),
            error_message="fallback_llm_servers 必须是字符串数组",
            error_code="invalid_fallback",
        )

        setting = _get_setting()
        known_names = {s.name for s in setting.llm_services}
        # 保序去重；剔除默认服务自身（兜底链不含首选）
        ordered: list[str] = []
        seen: set[str] = set()
        for item in raw:
            name = str(item).strip()
            if not name or name in seen:
                continue
            assertUtil.assertTrue(
                name in known_names,
                error_message=f"兜底服务 '{name}' 不存在于已配置的 LLM 服务中",
                error_code="unknown_fallback_service",
            )
            if name == setting.default_llm_server:
                continue
            seen.add(name)
            ordered.append(name)

        def mutator(s):
            s.fallback_llm_servers = ordered

        configUtil.update_setting(mutator)
        self.return_success(fallback_llm_servers=ordered)
