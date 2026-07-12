# digitallife v0.6.3

这是面向生产交付的稳定修复版本，包含 v0.6.2 容器/CI 修复及 SQLite 并发稳定性修复。

## 修复内容

- Docker 镜像使用稳定的 Node 20 构建阶段，容器默认监听 `0.0.0.0:8080`，并支持 `BIND_HOST` / `BIND_PORT`。
- Docker smoke test 显式传入监听配置并验证健康接口。
- 修复 Python 3.10 测试兼容性与 WebSocket 隔离测试断言。
- 修复团队成员替换时缺失 team scope 导致的 500。
- 修复房间创建在 SQLite 并发写入下的事务可见性和瞬时锁冲突。
- CI 后端测试改为串行 SQLite worker，避免测试环境共享数据库发生竞态。
- 诊断报告上传不再覆盖真正的测试失败原因。

## 验证

- GitHub Tests：Python 3.10 / 3.11、前端构建、浏览器 E2E、依赖审计全部通过。
- GitHub Docker：多架构构建和容器 smoke test 通过。
- GitHub macOS Release：arm64 社区包构建、签名完整性校验和 SHA-256 资产生成通过。
- 本地后端全量测试：1141 passed, 1 skipped。
- 两套前端测试与生产构建通过。
