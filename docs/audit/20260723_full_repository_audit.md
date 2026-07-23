# DigitalLife 全量代码库审计报告

审计日期：2026-07-23（UTC+08）  
代码库：`/Users/bytedance/kimi/DigitalLife`  
HEAD：`19dfbd8802a8ed23461009f2f2a45ccee3802063`（`feat: v0.9.0`）  
分支：`main`，领先 `origin/main` 4 个提交；同时审计当前未提交工作区。

## 执行摘要

新仓库比此前误审路径更新，包含经典、V2、V3 三套前端及 1,083 项后端测试。未发现 Critical 级已证实漏洞或仓库内高置信凭据。后端测试覆盖率 63%，超过 CI 的 60% 门槛；经典与 V3 前端全绿。当前工作区仍不宜直接发布：V2 存在一个确定失败测试，后端测试暴露 aiosqlite 线程在事件循环关闭后回调的资源生命周期告警，静态类型检查仍有大量错误，且工作区供应链/部署与 SQL 聚合改动应经过干净环境复验。

综合评级：**B**。风险统计：High 0、Medium 5、Low 4、Info 2。

## 范围与方法

- 资产：1,218 个 tracked 文件，Python/Tornado/Peewee 后端，三套 Vue 3 前端，TUI、SQLite migrations、Docker/systemd、GitHub Actions、发布脚本和测试。
- 工作区：35 个 tracked 文件变更（含二进制字体和删除文件），另有 migration 与测试等未跟踪文件；568 行新增、614 行删除。
- 自动验证：秘密扫描、三套 npm audit/test/build、后端 unit+integration+coverage、mypy。
- 人工复核：认证/授权、租户边界、WebSocket、文件与 Office 解析、SQL 聚合、异步资源、缓存、部署用户、供应链和工作区归因。

## 质量门禁

| 门禁 | 结果 |
|---|---|
| `scripts/security_scan.py` | 通过，无高置信秘密或敏感日志 |
| 后端 unit/integration | 1082 passed、1 skipped、1 warning |
| 后端覆盖率 | 63%（15192 statements，5586 missed） |
| 经典前端 | npm audit 0；24 files / 148 tests 通过；build 通过 |
| V2 前端 | npm audit 0；63 passed、1 failed；build 因测试链中止未执行 |
| V3 前端 | npm audit 0；3 files / 49 tests 通过；build 通过 |
| mypy | 失败；存在大量历史错误及工作区相关错误 |
| E2E/API 独立套件 | 本次未单独运行；后端 unit/integration 不包含 browser E2E |

## 发现

### NEW-M-001：V2 房间创建行为与测试契约不一致

- 严重度：Medium；置信度：高；归因：工作区引入或工作区暴露。
- 位置：`frontend-v2/src/components/settings-v2/TeamConfigurationEditor.vue`、对应 `TeamConfigurationEditor.test.ts`。
- 证据：测试期望 `agent_ids: [-1]`，实际为 `[7, -1]`，导致 V2 1/64 测试失败。
- 影响：新房间可能意外继承当前 Agent，或者测试契约已过时；两者都表明发布契约未确定。
- 建议：明确产品语义；若只应添加 operator，则修正组件；若继承成员是新需求，则更新测试并补充去重、删除成员和提交 payload 测试。发布前执行 V2 build。

### NEW-M-002：测试结束后 aiosqlite 工作线程仍向已关闭事件循环回调

- 严重度：Medium；置信度：高；归因：HEAD/工作区无法完全区分。
- 位置：持久化恢复路径、`src/service/ormService.py` 及测试 teardown。
- 证据：1082 项通过，但 pytest 报 `PytestUnhandledThreadExceptionWarning`：aiosqlite `call_soon_threadsafe` 遇到 `RuntimeError: Event loop is closed`。
- 影响：真实关闭/重载时可能遗留 DB 工作线程、丢失异常或产生竞态；当前 CI 若不把 warning 当错误会漏报。
- 建议：关闭 event loop 前 await 所有数据库连接/队列线程关闭；清理后台 task；CI 对该 warning 使用 `-W error`。增加 startup/shutdown 循环回归测试。

### NEW-M-003：静态类型门禁未通过且总量基线会掩盖替换型回归

- 严重度：Medium；置信度：高；归因：多数 HEAD 历史债务，部分工作区新增。
- 位置：`src/service/usageService.py:88,225`、`src/dal/db/gtRoomManager.py:29`、`src/controller/baseController.py:434,438`、`src/controller/wsController.py:301,367` 等。
- 证据：mypy 输出大量错误，包括新 SQL `in_` 表达式、批量鉴权查询和 async callback 签名；同时存在 safeHttpUtil 中 `ssl` 未定义等历史问题。
- 影响：真实接口错误可能藏在 ORM stub 噪声中；仅按错误总数比较允许旧错误消失、新错误加入而门禁仍通过。
- 建议：使用逐行 fingerprint baseline；给 Peewee model 字段添加正确 typing/plugin；先要求所有新增/修改文件零新增错误。

### NEW-M-004：GitHub Actions、基础镜像和 Python 依赖没有完全不可变锁定

- 严重度：Medium；置信度：高；归因：HEAD 已存在。
- 位置：`.github/workflows/*.yml`、`Dockerfile`、`requirements.txt`。
- 证据：Actions 使用 major tag，基础镜像使用浮动 tag，Python requirements 主要为兼容范围而非 hash lock。
- 影响：同一提交在不同日期可能执行不同上游代码或安装不同依赖；release 权限路径风险更高。
- 建议：Action 固定 commit SHA、镜像固定 digest、生产依赖使用 hash lock，生成并签名 SBOM/provenance。

### NEW-M-005：工作区 SQL JSON 聚合高度依赖 SQLite JSON1 语义和数据类型

- 严重度：Medium；置信度：中；归因：工作区引入。
- 位置：`src/service/usageService.py:26-249`。
- 证据：Python 容错提取被 `json_extract/json_type/NULLIF/SUM` 替代。虽然新增 integration tests 且后端套件通过，但 malformed JSON、数字字符串、布尔值、NaN/负值及未来非 SQLite 后端的语义可能不同；SQL 表达式也产生 mypy 错误。
- 影响：历史脏 metadata 可能使整个统计查询失败或改变 token 计数。
- 建议：迁移前扫描 `json_valid(metadata)`；SQL 添加有效 JSON 防护或存储层保证；建立 Python 旧实现与 SQL 新实现的属性/差分测试，覆盖异常类型和大数据集。

### NEW-L-006：注册串行锁只在单进程内生效

- 严重度：Low；置信度：高；归因：工作区修复不完整。
- 位置：`src/controller/authController.py:22`、注册 handler。
- 证据：模块级 `asyncio.Lock` 可避免单进程并发首用户注册，但多个进程/实例各有独立锁。
- 影响：多 worker 或多副本首次启动时仍可能竞争创建多个 ADMIN。
- 建议：在数据库事务内执行原子初始化；增加唯一“bootstrap consumed”状态或显式安装 token；多进程并发集成测试。

### NEW-L-007：Session 清理仅在 startup/成功登录触发

- 严重度：Low；置信度：高；归因：工作区引入。
- 位置：`src/controller/authController.py:25-39,83`。
- 影响：长时间运行但很少登录的实例仍保留过期 session；成功登录路径额外承担全表 DELETE。
- 建议：定时低频清理或数据库 TTL 作业，并保证 `expires_at` 索引；清理失败不应影响登录成功。

### NEW-L-008：WebSocket 序列化缓存仅以 event_id 为键

- 严重度：Low；置信度：中；归因：工作区引入。
- 位置：`src/controller/wsController.py:187-215`。
- 证据：全局 LRU 使用单个整数 event_id，不校验 topic/payload 身份。当前 messageBus 若保证全进程严格唯一则安全，但重置、测试 monkeypatch、热重载或不同发布源发生 ID 复用时会返回旧帧。
- 建议：键使用 `(event_id, topic)` 并保留 msg identity/hash；messageBus 重启时清空缓存；增加 ID 复用测试。

### NEW-L-009：经典前端字体 URL 构建产生未解析告警

- 严重度：Low；置信度：高；归因：工作区相关。
- 位置：`frontend/vite.config.ts` 与字体 CSS。
- 证据：构建报告 `/v1/fonts/...` 在 build time 未解析，保留到运行时。
- 影响：若反向代理或桌面打包未同步 `/v1/fonts`，生产字体会 404；构建不能验证资源存在。
- 建议：通过 Vite asset import/public base 的统一方式生成 URL，并在 E2E 中断言字体响应 200。

### NEW-I-010：覆盖率分布不均，关键控制器与入口偏低

- 严重度：Info。
- 证据：总覆盖率 63%，但 `roomController` 20%、`wsController` 22%、`settingController` 22%、`authController` 27%、`agentController` 29%；`skillImportService` 0%。
- 建议：除总阈值外增加关键安全模块阈值，优先权限、上传导入、WebSocket 和认证生命周期。

### NEW-I-011：工作区含重复二进制字体与未跟踪 migration

- 严重度：Info。
- 位置：`assets/fonts`、三套前端 public fonts、`assets/migrate/0019_agent_activity_room_id.sql`。
- 影响：相同字体多份维护易漂移；migration 若漏纳入发布将造成 ORM schema 与数据库不一致。
- 建议：构建时从单一字体源复制；发布门禁校验 model schema 与 migration 序列；明确纳入 0019。

## 正向观察

- 后端 1082 项通过，覆盖率实测 63%，用量服务达到 96%。
- 秘密扫描和三套 npm audit 均无发现。
- 经典前端进行了 manual chunk 拆分，最大入口降至约 448 kB；V3 构建约 325 kB。
- 工作区将 Office 解析移入线程并添加 20 MB 上限，改善事件循环阻塞风险。
- Room 批量鉴权保持 fail-closed 语义并消除 N+1；新增测试覆盖。
- deploy 脚本由 root 改为专用 non-login 用户，显著改善最小权限。
- 缓存改为有界 O(1) LRU；WebSocket 队列和序列化缓存均有容量限制。

## HEAD 与工作区归因

- HEAD 基线主要剩余风险：供应链不可变性、类型债务、关键控制器覆盖率不足、异步数据库关闭告警（归因尚不能完全确认）。
- 工作区修复：非 root systemd、Office 解析线程化、Room N+1、缓存 LRU、Session 清理、注册竞争、用量 SQL 聚合性能、WebSocket 序列化复用。
- 工作区新增/暴露风险：V2 测试失败、单进程注册锁边界、SQL JSON 兼容面、event_id 缓存键、字体 URL 告警及 migration 发布一致性。

## 整改路线

### P0（发布前）
1. 解决 V2 失败测试并完成 V2 production build。
2. 修复 aiosqlite teardown warning，使用 warning-as-error 重跑 1083 项。
3. 确认并纳入 migration 0019，执行升级/回滚和旧数据库恢复测试。
4. 对 usage SQL 与旧 Python 语义做异常 metadata 差分验证。

### P1（本迭代）
1. 将注册首管理员保证下沉为跨进程数据库原子约束。
2. 新增文件零 mypy 错误，并替换总量型债务基线。
3. 修复经典字体 URL 生产验证。
4. 固定 Actions SHA、镜像 digest 和生产 Python lock。

### P2/P3
1. 提高认证、Room、WebSocket、Skill import 控制器覆盖率。
2. 建立 SBOM、签名、provenance、镜像扫描和许可证清单。
3. 统一字体资产源，减少三套前端重复资源。

## 最终结论

该新仓库的实际质量明显优于此前路径：测试规模和覆盖率充分，工作区包含多项有价值的性能与安全修复。但当前工作区仍有明确红灯（V2 测试失败）和关闭生命周期告警。结论为：**HEAD 可在正式 CI 通过后作为候选基线；当前工作区需完成 P0 四项后再发布。**
