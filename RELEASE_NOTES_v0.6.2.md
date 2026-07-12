# digitallife v0.6.2

这是 v0.6.1 的修复发布，重点解决 CI 兼容性、Docker 容器启动和容器运行时配置问题。

## 修复内容

- 修复 Python 3.10 不支持 `asyncio.timeout()` 导致的测试失败，统一使用兼容的 `asyncio.wait_for()`。
- 修复 Docker 镜像默认监听配置：容器默认监听 `0.0.0.0:8080`，并支持 `BIND_HOST` / `BIND_PORT` 运行时覆盖。
- Docker smoke test 显式注入容器监听参数，验证真实 HTTP 健康检查。
- 增加绑定地址和端口环境变量校验，避免非法端口导致服务启动异常。
- README 版本章节与 v0.6.2 发布版本保持一致。

## 验证

- 后端全量测试：1142 passed, 1 skipped
- 经典前端：140 tests passed，生产构建通过
- V2 前端：46 tests passed，生产构建通过
- 版本一致性检查通过
