# digitallife v0.8.0

本版本在 v0.7.0 安全加固基础上，交付一批面向实际使用的功能与稳定性修复：联网搜索/网页抓取修复与多 Key 轮询、大模型服务预设与兜底链、Ghost 博客发布修复与团队结论自动发布、历史卷宗查看修复与「发起新话题」入口、各院专业技能，以及一批安全与并发一致性修复。

## 新功能

- **联网搜索 / 网页抓取**：`web_search` 支持 Tavily > Brave > Bing 三级引擎；新增专用搜索配置，支持多引擎、多 API Key 轮询与失败自动切换；`web_fetch` 增加响应体大小上限，防止超大响应耗尽内存。
- **大模型服务预设与兜底链**：新增常见服务商下拉预设（小米 MiMo、DeepSeek、火山方舟 AgentPlan / CodingPlan、Kimi、APINebula、自定义），选中即带默认接入地址与模型识别，仅需填写 API Key；支持配置多个模型、设置默认首选模型与兜底模型链，首选服务不可用时自动切换到下一个兜底服务。
- **Ghost 博客自动发布**：按 Ghost Admin API 规范（JWT + `source=html`）实现，后台可配置博客地址、Content / Admin API Key、发布状态；团队讨论完成后可自动将完整汇总结论发布到博客，全文无截断。
- **历史卷宗**：新增卷宗列表与详情页，历史结论可回看与下载；讨论完成后新增「发起新话题」入口，一键开启新一轮讨论。
- **各院专业技能**：为研究检索、写作文档、数据分析、代码工程 / 审查、合规审校、PPT / 分镜 / UI 设计、影视制作、市场调研、财务分析、政策起草、项目管理、内容运营等工作类型内置对口 Skills 并绑定到对应院 / 角色。

## 修复与加固

- 修复最终报告不落盘导致的「历史卷宗无法查看」，以及网络客户端数值超时不被接受导致网页抓取回退失败的问题。
- 安全：SSRF 防护（DNS Pinning + 逐跳重定向校验）、CSRF / 安全响应头、Claude SDK 危险工具审批门（可配置严格模式）、LLM 密钥脱敏与请求日志降级、限流内存清理、登录时序防用户名枚举、`cookie_secret` 持久化、上传路径沙箱复验、zip 炸弹真流式解压上限、Google 密钥改用请求头承载。冲突项默认放行，可经 `setting.security` 在生产开启严格模式。
- 并发与一致性：轮次 Function Calling 总步数熔断、房间级调度熔断、消费者与事件回调异常检索（避免 Agent 静默卡死）、Agent 历史写入原子性与事务级重试、Token 估算移出事件循环、超长上下文压缩收敛。

## 验证

- 本地后端全量测试：1031 passed, 1 skipped，0 failed。
- 两套前端生产构建通过（frontend / frontend-v2）。
- 搜索真机联调（Tavily / Brave）与 Ghost 博客端到端联调（发布 → 读回校验完整无截断 → 删除）通过。

---

This release builds on the v0.7.0 security hardening with practical features and stability fixes: web search/fetch repair with multi-key rotation, LLM provider presets and fallback chains, Ghost blog auto-publishing of complete conclusions, dossier history viewing with a "start new topic" entry, per-department skills, and a batch of security and concurrency-consistency fixes.

- **Web search / fetch**: three-tier engines (Tavily > Brave > Bing), dedicated search config with multi-key rotation and automatic failover; `web_fetch` now caps response body size.
- **LLM provider presets & fallback**: dropdown presets (Xiaomi MiMo, DeepSeek, Volcengine Ark AgentPlan/CodingPlan, Kimi, APINebula, custom) auto-filling base URL and models — only the API key is required; configure multiple models, a preferred default, and a fallback chain that switches automatically when the primary is unavailable.
- **Ghost auto-publishing**: spec-compliant Admin API (JWT + `source=html`); the full team conclusion is published without truncation on completion.
- **Dossier history** viewing/download plus a "start new topic" entry after a discussion ends.
- **Per-department skills** for research, writing, data analysis, engineering, review, design, media, and more.
- **Security & concurrency fixes**: SSRF/CSRF hardening (configurable strict mode via `setting.security`), key redaction, rate-limit cleanup, login timing hardening, persisted `cookie_secret`, streaming zip-bomb caps, turn step circuit breaker, async exception retrieval, atomic history writes.

**Full Changelog**: https://github.com/suvlife/DigitalLife/compare/v0.7.0...v0.8.0
