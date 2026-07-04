import ipaddress
import json
import logging
import time
from urllib.parse import urlparse

from pydantic import BaseModel, ValidationError

from constants import LlmServiceType
from controller.baseController import BaseHandler
from service import schedulerService
from util import assertUtil, configUtil, llmApiUtil
from util.configTypes import LlmServiceConfig

logger = logging.getLogger(__name__)

# LiteLLM custom_llm_provider 映射（与 llmService 保持一致）
_TYPE_TO_PROVIDER = {
    LlmServiceType.OPENAI_COMPATIBLE: "openai",
    LlmServiceType.ANTHROPIC: "anthropic",
    LlmServiceType.GOOGLE: "gemini",
    LlmServiceType.DEEPSEEK: "deepseek",
}

# 云元数据端点（SSRF 高危目标）
_METADATA_HOSTS = {"169.254.169.254", "metadata.google.internal"}


def _assert_safe_llm_url(base_url: str) -> None:
    """校验 LLM base_url 不指向内网/回环/元数据端点，防止 SSRF。

    仅允许 http/https scheme，拒绝 loopback/私有/链路本地/保留段 IP，
    以及云元数据主机名。对域名做解析后再次校验（防 DNS rebinding 的
    基础防护；完整防 rebinding 需在连接层 pin IP）。
    """
    if not base_url:
        return
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https"):
        raise assertUtil.TogoException(
            error_code="unsafe_url",
            error_message=f"base_url 仅允许 http/https scheme: {base_url}",
        ) if hasattr(assertUtil, "TogoException") else ValueError(f"unsafe scheme: {base_url}")
    hostname = parsed.hostname or ""
    if not hostname:
        raise ValueError(f"base_url 缺少 hostname: {base_url}")

    if hostname in _METADATA_HOSTS:
        raise ValueError(f"base_url 指向云元数据端点，已拒绝: {hostname}")

    # IPv4/IPv6 直接校验
    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValueError(f"base_url 指向内网/保留地址，已拒绝: {hostname}")
    except ValueError:
        # 非 IP 字面量，作为域名处理：拒绝 localhost 等已知内网域名
        if hostname in ("localhost", "ip6-localhost", "ip6-loopback"):
            raise ValueError(f"base_url 指向回环地址，已拒绝: {hostname}")


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
    """GET /config/llm_services/list.json"""

    async def get(self) -> None:
        setting = _get_setting()
        services = [_serialize_llm_service(service) for service in setting.llm_services]
        self.return_json({
            "llm_services": services,
            "default_llm_server": setting.default_llm_server,
        })


class LlmServiceCreateHandler(BaseHandler):
    """POST /config/llm_services/create.json"""

    async def post(self) -> None:
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

        # 校验 base_url 格式
        assertUtil.assertTrue(
            new_service.base_url.startswith("http://") or new_service.base_url.startswith("https://"),
            error_message="base_url 必须以 http:// 或 https:// 开头",
            error_code="invalid_base_url",
        )

        def mutator(s):
            s.llm_services.append(new_service)

        configUtil.update_setting(mutator)
        self.return_json({"status": "ok", "index": len(setting.llm_services) - 1})


class LlmServiceModifyHandler(BaseHandler):
    """POST /config/llm_services/{index}/modify.json"""

    async def post(self, index_str: str) -> None:
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

        # 校验 base_url 格式
        if "base_url" in updates:
            url = updates["base_url"]
            assertUtil.assertTrue(
                isinstance(url, str) and (url.startswith("http://") or url.startswith("https://")),
                error_message="base_url 必须以 http:// 或 https:// 开头",
                error_code="invalid_base_url",
            )

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

        if not configUtil.is_initialized():
            schedulerService.stop_schedule("无可用的大模型服务")

        self.return_json({"status": "ok"})


class LlmServiceDeleteHandler(BaseHandler):
    """POST /config/llm_services/{index}/delete.json"""

    async def post(self, index_str: str) -> None:
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

        # 删除服务后检查：若无可用 LLM 服务，阻塞调度
        if not configUtil.is_initialized():
            schedulerService.stop_schedule("无可用的大模型服务")

        self.return_json({"status": "ok", "deleted_name": service.name})


class LlmServiceSetDefaultHandler(BaseHandler):
    """POST /config/llm_services/{index}/set_default.json"""

    async def post(self, index_str: str) -> None:
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
    """向目标 LLM 服务发送一个最小 Agent 风格请求，验证真实推理链路。"""
    provider = _TYPE_TO_PROVIDER.get(config.type)

    request = llmApiUtil.build_agent_probe_request(
        model=config.model,
        provider_params=config.provider_params,
    )

    start_time = time.monotonic()
    response = await llmApiUtil.send_request_stream(
        request,
        config.base_url,
        config.api_key,
        custom_llm_provider=provider,
        extra_headers=config.extra_headers,
    )
    duration_ms = int((time.monotonic() - start_time) * 1000)

    return {
        "model": config.model,
        "response_text": response.choices[0].message.content if response.choices else "",
        "duration_ms": duration_ms,
        "usage": response.usage.model_dump() if response.usage else None,
        "test_mode": "agent_probe_stream_with_tools",
    }


_SUPPORTED_LANGUAGES = {"zh-CN", "en"}


class LanguageHandler(BaseHandler):
    """POST /config/language.json — 设置界面语言偏好。"""

    async def post(self) -> None:
        body = json.loads(self.request.body)
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
