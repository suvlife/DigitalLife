# digitallife v0.6.1

这是一次面向生产可靠性、安全隔离和 V2 完整体验的修复版本。

## 重点更新

- V2 成为默认入口，经典控制台独立保留在 `/v1/`，旧 `/v2/...` 链接兼容重定向。
- 修复所有院“入殿问策”主房间识别和 `OPERATOR(-1)` 无法发送消息。
- V2 设置补齐团队成员、角色、模型、Driver、组织树、研究室、房间和预设导入管理。
- 卷宗详情使用 Run 范围快照与时间线，不再混入其他运行的当前数据。
- 修复公共团队 Run REST 越权和同团队并发 Run 事件串线。
- WebSocket 支持 Cookie 登录、多租户事件隔离和共享 Scope 缓存。
- Run 最终状态原子化，报告文件原子写入，SQLite 启用 WAL、外键和锁冲突有限重试。
- Ghost 使用稳定 slug、Worker lease 和 CAS，避免超时重试产生重复文章。
- Ghost 与正常 Agent LLM 推理均启用 DNS 固定、私网拦截和重定向保护。
- 文件下载改为流式分块，增加大小/并发限制、安全 UTF-8 文件名及 Bearer 下载支持。
- Release ZIP 与 SHA-256 同批生成验证；CI 增加浏览器 E2E、依赖漏洞、密钥和容器烟测门禁。

## 数据库升级

本版本新增迁移：

```text
0018_blog_publication_leases.sql
```

部署前建议运行：

```bash
python scripts/backup_and_migrate.py --config-dir /path/to/storage
```

脚本会创建并验证数据库备份、执行迁移并输出回滚命令。

## 验证

- 后端：1140 passed，1 skipped
- V2：46 tests passed，production build passed
- 经典前端：140 tests passed，production build passed
- Playwright：2 browser journeys passed
- Python / npm 生产依赖：无已知高危漏洞
