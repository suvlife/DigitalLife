# Frontend V2（江湖书院）

独立的 Vue 3 + TypeScript + Vite 应用，生产 base 为 `/v2/`，与经典
`frontend/` 并存，不替换现有控制台。

## 本地开发

```bash
cd frontend-v2
npm ci
npm run dev       # http://localhost:8182/v2/
npm run test:run
npm run build
```

## 已集成能力

- Tornado `/v2/(.*)` SPA fallback；
- `/runs/current.json`、`/runs/list.json`、`/runs/{id}.json`；
- Run 房间快照、时间线和最终答案接口；
- teams / rooms / agents / messages / tasks / activities 数据聚合；
- WebSocket `run_*`、`room_run_changed`、`blog_publish_changed` 等事件解析；
- 真实任务和房间进度展示，不生成时间型假进度；
- 院落、房间、NPC、对话时间线、进度卷轴、任务侧栏和归档页面；
- Markdown 展示、移动端布局与 reduced-motion 降级。

## 构建集成

仓库根目录执行：

```bash
.venv/bin/python scripts/build_frontend.py --target v2 --install
```

构建结果会同步至 `assets/frontend-v2/`，该目录为本地生成产物，不提交到 Git。
Dockerfile 会在镜像构建阶段直接构建并复制 V2 静态文件。

## 当前边界

V2 当前主要负责团队导航、任务观察、实时进度、历史归档与最终结果展示。
LLM、团队、房间、Agent、Skill 和 Ghost 等完整配置仍在经典控制台中完成。
取消 Run、房间级重试等写接口尚未提供。
