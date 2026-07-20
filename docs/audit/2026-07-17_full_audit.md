# DigitalLife 全库审计报告（2026-07-17）

> 审计范围：后端 `src/` 全部、`frontend/`、`frontend-v2/`、`tui/`、`scripts/`、部署配置。
> 方法：环境搭建 + 全部测试套件实测 + 91 个 HTTP 端点扫描 + 六个维度并行代码审计。
> 环境：Python 3.12.12（.venv，uv 创建）、Node 20.20.2 / 26.5.0 双版本对照、macOS arm64。

## 一、测试与实测结果

| 项目 | 结果 |
|---|---|
| 后端 unit + integration | 1029 通过 / **7 失败**（均为真问题，见 A1/A2） |
| 后端 API 测试（tests/api，真实后端子进程 + Mock LLM） | **127 全过** |
| 91 个 HTTP 端点扫描 | GET 无 5xx；**4 个 POST 接口非法输入返回 500**（见 A3） |
| WebSocket 握手 / SPA 路由 | 正常（`/` 需先跑 `scripts/build_frontend.py` 同步产物到 `assets/`，否则默认入口 404） |
| frontend vitest | Node 20：143 全过；**Node 26：21 失败** |
| frontend-v2 vitest | Node 20：53 全过；**Node 26：17 失败** |

环境类发现：

- `requirements.txt` 缺 `pytest-xdist`（`scripts/run_tests.sh` 默认 `-n auto --dist loadscope` 直接报错）。
- 仓库无 `.nvmrc`/`engines` 锁定 Node 版本；Node ≥25 的原生 `localStorage` 与 happy-dom 冲突，两个前端 vitest 全挂（CI 固定 Node 20 所以未暴露）。

## 二、实证确认的问题（最高优先级）

### A1. LLM 的 SSRF DNS pinning 全面失效（安全回归，6 个单测失败）

- 位置：`src/util/llmApiUtil/client.py:386-388` + `src/util/safeHttpUtil.py:175-185`
- `_build_secure_litellm_client` 恒以 `allow_private=True` 调 `create_pinned_client_session`，命中早退分支：**所有 LLM 流量**（不止本地 Ollama）都没有 DNS 固定、没有重定向拦截、没有 `trust_env=False`。被配置的上游可 302 到私网/云元数据地址。
- v0.8.7~v0.8.9 为修代理环境连接一刀切放开，把公网端点也放开了；`client.py:393-402` 的 H10 注释仍在宣称有防护，与代码不符。
- 失败测试：`tests/unit/service/test_llm_client.py` 6 个用例（pinning、redirect 拒绝、4 个 provider transport），测试本身是正确的防护契约。
- 修复方向：按解析结果分流——`resolve_public_addresses` 能拿到公网地址则走 pinned 分支；仅当确为私网/回环/代理假 IP（198.18.x.x）时降级为普通会话。

### A2. Run 关联串线：缺 run_id 的房间事件未丢弃（1 个集成测试失败）

- 位置：`src/service/runService.py:599-602`
- 房间存在多个活动 Run 关联、事件不带 `run_id` 时，代码取"最新关联"继续执行，把另一个 Run 的 room_run 标为 COMPLETED。`tests/integration/test_run_service.py::test_concurrent_runs_use_explicit_room_association_without_cross_talk` 明确要求此类旧事件必须丢弃。
- 修复方向：多关联且无 run_id 时返回 None（不猜测）。

### A3. 参数校验失败返回 500（端点实测复现）

- 空 body POST `/role_templates/create.json`、`/role_templates/1/modify.json`、`/teams/create.json`、`/teams/1/rooms/create.json` 均返回 500。
- 日志确认为 `src/controller/baseController.py:409` `parse_request` 未捕获 pydantic `ValidationError`。同类错误全仓三种行为并存（部分 handler 手工 catch 返回 400，部分 500）。
- 另有一批 query 参数裸 `int()` 未捕获：`roomController.py:138,193,195`、`agentController.py:57,197,226`、`activityController.py:21-22,61-63,87`、`usageController.py:15-16,54,78`，应统一用已有的 `get_int_argument()`。
- 修复方向：`parse_request` 统一捕获 `ValidationError` → 400 + `format_validation_error`。

### A4. `verify_presets.py` 验证的是 /tmp 残留副本（实测崩溃）

- 位置：`verify_presets.py:11-13`，`ROOT = Path("/tmp/digitallife")` 硬编码。干净机器上直接 `FileNotFoundError`；原作者机器上验证的是旧副本，PASS 不可信。一次性脚本误提交。

## 三、审计发现汇总

### 🔴 高严重度

#### 安全

1. **xheaders 无条件信任 XFF，限流/IP 审计可伪造**：`src/backend_main.py:254-256` + `src/controller/baseController.py:182`。直连部署时轮换 `X-Forwarded-For` 即可绕过全部速率限制（含登录 30 次/分）并污染审计 IP。应仅在配置可信代理时启用 xheaders。
2. **Gemini API key 可能落盘**：`src/util/llmApiUtil/client.py:236,264-271`。错误日志原样记录 `response.url`，litellm gemini 适配器把 key 放 `?key=` query。需 query 脱敏（`key=`/`api_key=`/`access_token=`）。
3. **规则命中日志明文打印 provider_params**：`src/service/llmService/llmRequestRules.py:217-223`，白名单允许的 `tavily_api_key` 会写入日志。应掩码。

#### 可用性/正确性

4. **ClaudeSdkDriver turn 循环无总步数上限**：`src/service/agentService/driver/claudeSdkDriver.py:303-333`。`has_tool_progress` 即清零计数无限 re-query，异常模型可单任务无限烧配额（native 路径有 `_MAX_TURN_STEPS=80` 熔断，SDK 路径漏防）。
5. **RoomScheduler 锁只护 finish 不护 on_message，真实竞态**：`src/service/roomService/roomScheduler.py:104,148-152,172-199`。finish 的 `await persist_state()` 期间 on_message 无锁改状态，陈旧 next_id 会导致两个 Agent 同时被唤醒。
6. **任务失败后无重驱动，房间永久卡 SCHEDULING**：`src/service/agentService/agentTaskConsumer.py:224-228`。FAILED 即 break，全系统无看门狗，retry_count 机制永远触发不到，只能人工 `/agents/{id}/resume.json`。
7. **get_current_user() 同步 DB 查询阻塞事件循环且每请求重复 3~5 次**：`src/controller/baseController.py:235-256`。`db.allow_sync()` + 独立 sqlite 连接 + 异常吞掉误判 401。`wsController.py:308-324` 已有正确异步实现可复用；应做请求级缓存。
8. **frontend-v2 主殿崩溃**：`frontend-v2/src/realtime/events.ts:11` 把 `publication` 硬塞为 undefined，展开合并覆盖 REST 快照正常值，`CentralHall.vue:2` 访问 `.status` 白屏。且唯一能救回的 `publication_changed` 事件被丢弃（见中危 M1），无法自愈。
9. **frontend 鉴权开启时 WS 重连永久卡"重连中"**：`frontend/src/realtime/wsClient.ts:149`。认证成功条件写死 `=== 'connecting'`，重连态永不迁移，断线期间数据不补齐；现有测试全部 `authEnabled=false` 零覆盖。
10. **frontend「退出登录」不退出**：`frontend/src/components/layout/TopBar.vue:200-210`。不调 `logout()`、不断 WS、不清 `currentUser`。
11. **部署脚本管道掩盖构建失败**：`deploy/update.sh:40,44,50`、`deploy/deploy.sh:69`。有 `set -e` 无 `pipefail`，`pip install | tail -3` / `npm build | tail -3` 失败后照样 systemctl start 上线坏版本。

### 🟡 中严重度

#### 性能（后端）

- **failover 重试放大**：`src/service/llmService/core.py:37-38,380-515`。兜底切换要等单服务 9 次重试 ×180s 超时耗尽，黑洞上游单请求可卡约 30 分钟，期间占全局并发槽。应失败 2~3 次即切换或加熔断。
- **SSRF DNS 解析同步阻塞事件循环**：`src/util/safeHttpUtil.py:84`。慢 DNS 冻结整个 tornado 循环（web_fetch 单次至少解析 2 次，每重定向跳 +1 次）。改 `loop.getaddrinfo` 异步化，顺带消除 web_fetch 双重解析。
- **用量统计同一窗口全表扫描 4 遍 + Python 聚合**：`src/service/usageService.py:217-233`（62/92/139/174）。应下推 SQL 聚合（写入侧冗余数值列）或短时缓存。
- **`/activities.json?room_id=` 走 json_extract 无索引全表扫描**：`src/dal/db/gtAgentActivityManager.py:119-121`。应加独立 room_id 列 + 索引。
- **N+1 多处**：`/rooms/list.json` 按团队串行（`roomController.py:146-155`）；`/rooms/last_messages.json` 逐房间串行归属校验 2N 次（`:170-173`）；prompt 构建 2N 次重复查（`promptBuilder.py:118-129`）；归属校验与业务查询同请求 team/room 各查 2~3 遍（`baseController.py:380-398` 等）。
- **compact 截断在事件循环同步跑 token_counter**：`src/service/agentService/compact.py:176-222`（主路径已有 executor 封装，截断路径漏修）。
- **Office 文件解析 / 5MB HTML 正则在事件循环同步执行**：`src/service/artifactService.py:48-135`、`src/service/funcToolService/webTools.py:139-147`。应 `asyncio.to_thread` + 输入大小上限。
- **每次 LLM 请求（含每次重试）新建销毁 aiohttp session**：`client.py:448,522,548,585`。零连接复用；配合 A1 修复按 (base_url, provider) 缓存 session。
- **消息无上限**：GET 消息不传 limit 全量拉取（`roomController.py:191-201` + `gtRoomMessageManager.py:72-73`）；房间内存消息只增不删、恢复全量加载（`messageStore.py:20-34`、`roomService/core.py:107`）。
- **WS 每事件每连接重复序列化 + 全局 indent=4**：`wsController.py:439-444` + `src/util/jsonUtil.py:33-42`。广播应在发布侧序列化一次复用；线上 indent 置 None。
- **deptService 读旧缓存**：`src/service/deptService.py:221-225,326-334`。先读缓存树同步房间、后才失效，stale read 几乎必触发。
- **熔断阈值误杀**：`src/service/schedulerService.py:25-42`。按调度事件数计，6 人房间跑约 83 轮即被误熔断；房间自定义 max_rounds 不被考虑。
- **Agent 历史 seq 平移是 N 次单条 UPDATE**：`gtAgentHistoryManager.py:70-88`。可用两段式单语句。
- **每次推理后 post-check 全历史重算 token**（`agentTurnRunner.py:702-708`）、每 step 查一次控制房间（`:309-315`）、`_team_config` 缓存字段是死代码每次推理查 team（`:957-966`）。

#### 逻辑（后端）

- **consumer stop/start 竞态**：`agentTaskConsumer.py:79-85,122-132,196`。stop 不等取消完成，新旧 consumer 可并发跑同一 RUNNING 任务共享 `_history`。
- **InjectPromptCacheControlRule 死代码**：`llmRequestRules.py:150-156,186-190` + `configTypes.py:53-77`。配置校验使匹配条件永不成立，Anthropic cache_control 注入从不发生。
- **Ghost 发布契约漏洞**：`ghostService.py:405-468`。200 但非 JSON 穿透 retryable 契约；`UnsafeUrlError`（确定性配置错误）被标可重试无意义退避。
- **`_load_room` 锁契约违反**（`roomService/core.py:196-201`）；**`upsert_room` 不维护新成员已读游标**（`:238-262`）；**`delete_managed_room` 不清运行时与存量任务**（`:564-580`）。
- **上传 50MB 限制 vs 服务器 20MB 上限矛盾**：`roomController.py:526,556-559` vs `backend_main.py:257-258`，50MB 检查是死代码。
- **两条 Agent 历史恢复路径口径不一致**：`persistenceService.py:36-72` 全量加载 Python 裁剪取最后一个 compact vs `gtAgentHistoryManager.py:177-212` SQL 取第一个之后，应统一 SQL 版并修正 first/last 语义。
- **启动恢复 assert sender 存在**：`roomService/core.py:117-122`。sender 被清理则整个恢复 AssertionError 中断；应批量预取 + 降级 display_name。
- **skill 全局索引线程中重建，读者可见半填充状态**：`skillImportService.py:189,214,236` + `skillService.py:60-78`。应构建完成后原子替换。
- **`reload_team` 工具永久 await 无超时兜底**：`funcToolService/tools.py:376-382`。

#### 前后端契约 / 调用方式

- **frontend-v2 三处字段与后端 payload 对不上**：
  - `blog_publish_changed` 缺 team_id → 100% 被丢弃（`events.ts:13`；后端 `runService.py:573-580` 补 team_id 即可）；
  - `room_run_changed` 读 `current_activity_type`/`activity_label`，真实字段是 `current_activity`（`events.ts:12`）→ 实时 NPC 状态失效；
  - REST 消息 `id` 只读 `db_id` 恒 null（`client.ts:142`，后端字段是 `id`）→ WS 去重失效、消息重复显示。
- **后端日期格式 `%Y-%m-%d %H:%M:%S.%f` 非 ISO**：Safari 全部 "Invalid Date"、排序 NaN（v2 DialogueTimeline/SpeakerTimeline/world.ts/domain/status.ts/TaskSidebar）。
- **竞态一批**：旧版切房间旧响应覆盖新选择（`useConsoleRuntimeState.ts:48-66`，高）；旧版设置页团队详情（`useSettingsTeamDetailState.ts:58-73`）；v2 reconcile 在途丢事件（`world.ts:69`）；v2 归档页被实时事件污染（`world.ts:18,23,62,70`）；usage 快照/增量竞态（`usageStore.ts:20-52`）；v2 SettingsPage loadTeamDetail 无 requestId（`SettingsPage.vue:117-125`）。
- **N+1 请求风暴**：v2 每房间单独拉消息（`world.ts:59,69`，后端批量端点 `/rooms/last_messages.json` 未用）；旧版设置页每团队 3 请求（`useTeamSummaries.ts:18-51`）；TUI 每房间拉全量历史只取最后一条（`tui/app.py:100-114`）。
- **WS 客户端缺陷（旧版）**：首连无超时保护、无心跳、1008 未处理（`wsClient.ts:98-108,143-191`）；启动时 `startRealtimeClient()` 先于 `checkSystemStatus()` 有 authEnabled 竞态（`App.vue:349-350`）。
- **TUI 发消息网络异常直接崩溃 app**：`tui/app.py:386-390` 未捕获 `ClientError`。

#### 前端性能

- **frontend-v2 打 14.7MB woff2 字体**（默认入口首屏，两个 lxgw-wenkai 文件各 7MB+）。
- **frontend bundle 738KB 无代码分割**（构建警告 >500KB）。
- **旧版房间消息无上限 + 每条新消息 O(n log n) 全量排序 + deep watch**：`runtimeStore.ts:524-528`、`MessageStream.vue:238-253`；长会话数千条后每消息全量拷贝排序，MessageStream 无虚拟滚动。
- **旧版文件上传成功触发整页 refreshAll()（5 请求全量重拉）**：`ConsoleChatPanel.vue:195-198`。
- **v2 fallbackRun 每事件 O(n²) 重算**：`world.ts:22,10`；reconcile 是全量 5 端点 + 每房间 1 请求。
- **v2 每条消息各 `new MarkdownIt()`**（`MarkdownContent.vue:1`）；`filter:brightness` 无限动画每帧重绘（`global.css:8`）。
- **v2 RoomPage 同房间消息最多连发 3 次请求**：`RoomPage.vue:22`。

#### 工具链 / 部署

- **`.dockerignore` 漏 `frontend/node_modules`**（`:10-11`，只排除根 + frontend-v2）：构建上下文上传几百 MB 且污染 `npm ci` 层，产物不可复现。改 `**/node_modules`。
- **运行中 cp 备份 SQLite**：`deploy/update.sh:17-24` 先备份后停服务，WAL 下可能出坏备份；仓库已有正确的 `scripts/backup_and_migrate.py`。
- **systemd 以 root 运行**（`deploy/deploy.sh:92`）与 Dockerfile 非 root（uid 10001）矛盾。
- **`deploy.sh` 声称支持 Ubuntu 22.04 但官方源无 python3.11**（`:4,13,27`），需 deadsnakes PPA；多处 `2>/dev/null` 吞错误（`:31,61-62`）。
- **nginx heredoc 引号定界符变量不生效**（`deploy.sh:109-136`）；`deploy/nginx.conf:72-76` `proxy_cache_valid` 无 `proxy_cache_path` 是空操作。
- **启停脚本缺陷**：`scripts/start_backend.sh:6` 重定向到不存在的 `logs/` 目录，全新 clone 首次运行直接失败；启动无端口/存活检查；`stop_backend.sh`/`stop_tui.sh` 不校验 PID 进程名可能误杀。
- **`build_release.py:143-149` Apple 应用专用密码明文打进终端/CI 日志**。
- **`run_tests.sh`/`run_mypy.sh` 依赖调用时 CWD**；`run_mypy.sh` 用 eval 拼命令。

### 🟢 低严重度（择要）

- 首用户注册 TOCTOU 可产生多 ADMIN（`authController.py:144-163`）；过期 session 永不清理表无界增长（`gtUser.py:70-79`）。
- `SkillImportHandler` JSON 分支永不成立死代码（`settingController.py:556-566`）；两处 handler 绕过 parse_request 直接 json.loads（`deptController.py:32`、`settingController.py:198`）。
- `UpdateRoomRequest.type` 裸 str 非法值 500（`roomController.py:34,449-450`）；`/role_templates/([^/]+)` 路由不限数字 500（`route.py:162-164`）。
- WS 旧式首帧 token 鉴权失败无限流可爆破（`wsController.py:278-306`）。
- `GtDept.children` 类级可变默认值（`gtDept.py:32`）。
- 无界内存结构：`_SERVICE_REQUEST_GATES`/`_API_KEY_ROTATION`/`_search_rotation`（llmService/webTools）、`_task_create_locks`/`_room_turn_counts`（schedulerService）、TUI 日志无轮转（`tui_main.py:44-46`）。
- `cacheUtil` 满容后 O(n) 扫描且是假 LRU（`cacheUtil.py:159-167`）。
- `ormService.backup_database` 同步阻塞（`:289-308`）；`update_setting` 事件循环上持 threading.Lock 同步读写文件（`configUtil.py:358-434`）。
- `webTools._get_session` 惰性初始化竞态漏 session（`webTools.py:33-38`）。
- controller 调 service 私有方法（`roomController.py:294`）；`_ensure_special_agents_exist` 绕过 dal 违反分层（`agentService/core.py:60-70`）；Agent facade 穿透多层私有成员 + 热更新持全局锁跨秒级 driver 启动（`agent.py:57-71`、`agentService/core.py:223-277`）。
- `escalate_to_immediate` 不走 store 锁与 flush 并发可致 seq 分叉（`messageStore.py:172-194`）；`get_unread_messages` 无新消息也 persist（`chatRoom.py:179-183`）；SDK 工具回调 json.loads 无保护（`claudeSdkDriver.py:271-274`）；`activate_rooms` 遍历注册表未快照（`roomService/core.py:583-591`）；`ChatRoom._max_rounds` 与 `RoomScheduler._effective_max_rounds` 重复实现且语义不一致。
- 前端：FileCard ObjectURL 泄漏（`FileCard.vue:80-110`）；`api.ts:203-213` makeWsUrl 丢 base 路径前缀；`avatar.ts` 硬编码 `/avatars/` 与 vite base 不一致；`i18n.ts:29` 裸 fetch 绕过封装；硬编码中文绕过 i18n 多处；`SettingsPage.vue:290-298` 死请求；`AgentTaskPanel.vue:132-152` 重复拉取；`TeamMemberGraph.vue:102` 内容变化即重置画布；v2 `client.ts:25` GET 强加 JSON Content-Type 触发 CORS 预检；`client.ts:19` revokeObjectURL 过早；`client.ts:23-28` 无超时；`client.ts:172` 相对 BASE 时 new URL 抛错；v2 `socket.ts:14` 重连无 jitter；v2 归档页历史成员名退化"大师 {id}"（后端 sender_display_name 非 DB 字段不序列化）；v2 `RoomPage.vue:16-17` 小写比较 state 永不命中死代码。
- `package_windows.sh:35-36` heredoc 版本号变字面垃圾；`docker-compose.yml` version 字段废弃、健康检查重复、无日志轮转；`deploy/watchdog.sh` 告警只有日志、计数无界、整数比较未引用；`deploy/auto-update.sh` 无并发锁、任一前端变更双前端全量重建；`tui/widgets.py:243-244` 未读 0 时显示字面 `[0]` 且房间名未转义 markup；`tui/app.py:65-66` 直接写 stdout 转义序列。

### 审计确认的良好实践（不误报）

DAL 事务级重试、`claim_due` CAS 租约、`transition_task_status` 原子 CAS、窗口函数批量查 last_messages、热路径索引齐全、WS 发送队列背压、上传/下载沙箱路径校验、skill zip 导入 Zip-Slip/炸弹双防护且走线程池、密钥不落 API 响应（has_api_key 布尔）、extra_headers 日志脱敏、LLM provider_params 保留字校验 + 白名单透传、流式产出后禁止整体重试/failover、activity 进度 200ms 节流、SQLite 连接池 + busy 重试、`scripts/backup_and_migrate.py` backup API + 完整性校验、Dockerfile 多阶段构建层缓存顺序正确。

## 四、修复顺序（执行中）

1. **A1** SSRF pinning 分流（修完 6 个测试转绿）
2. **frontend-v2 H1** 崩溃止血 + M1/M2/M3 契约字段（events.ts 全部归一化分支对照后端 payload 核对）
3. **A2** Run 串线 + **A3** parse_request 统一 400
4. **frontend H1** WS 重连状态机（补 authEnabled=true 用例）+ **后端任务失败重驱动**
5. **RoomScheduler 竞态** + **SDK driver 步数上限**
6. 中危性能项：failover 重试、DNS 异步化、usage SQL 聚合、N+1 批量接口
