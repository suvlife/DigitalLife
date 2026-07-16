
# 数字人生（DigitalLife）🚀

<p align="center">
  面向复杂任务的开源多智能体协作平台：让多个 LLM Agent 在团队、部门与聊天室中自主讨论、调用工具、追踪进度并汇总最终答案。
</p>

<p align="center">
  <a href="README.md">中文</a> · <a href="README_EN.md">English</a> ·
  <a href="https://github.com/suvlife/DigitalLife/releases">Releases</a> ·
  <a href="deploy/README.md">部署指南</a>
</p>

<p align="center">
  <img alt="Version" src="https://img.shields.io/badge/version-0.8.9-blue">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white">
  <img alt="Node.js" src="https://img.shields.io/badge/Node.js-20%2B-339933?logo=nodedotjs&logoColor=white">
  <img alt="Backend" src="https://img.shields.io/badge/backend-Tornado-orange">
  <img alt="Frontend" src="https://img.shields.io/badge/frontend-Vue%203%20%2B%20TypeScript-42b883">
  <img alt="Platform" src="https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey">
</p>

> [!IMPORTANT]
> 本项目会调用第三方大模型与可选的搜索、Ghost CMS 等服务，相关费用、数据处理规则与内容合规责任由对应服务和使用者承担。股票、命理等内置团队的输出仅用于研究与辅助分析，不构成投资、医疗、法律或其他专业建议。

---

## 目录

- [项目简介](#项目简介)
- [v0.8.4 重点更新](#v084-重点更新)
- [核心能力](#核心能力)
- [内置团队](#内置团队)
- [系统架构](#系统架构)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [Web 界面与使用流程](#web-界面与使用流程)
- [API 与实时事件](#api-与实时事件)
- [Ghost 博客发布](#ghost-博客发布)
- [数据、安全与生产部署](#数据安全与生产部署)
- [开发、测试与发布](#开发测试与发布)
- [常见问题](#常见问题)
- [项目结构](#项目结构)
- [路线与已知边界](#路线与已知边界)
- [许可证与致谢](#许可证与致谢)

---

## 项目简介

**数字人生**是一套 Python + Vue 3 构建的多智能体协作系统。与固定 DAG 或单 Agent 问答不同，它把复杂任务放进一个可配置的“数字组织”中：

1. 用户向团队或房间提出任务；
2. 调度器根据房间、部门、Agent 状态和团队策略选择下一位参与者；
3. Agent 使用不同模型进行分析，并可通过 TSP / Function Calling 调用工具；
4. WebSocket 将思考、回复、工具调用、重试与运行进度实时推送到前端；
5. 汇总角色提交最终结论；
6. 可选地将最终结论持久化并发布到 Ghost CMS。

项目同时提供三种交互入口：

| 入口 | 路径/目录 | 适用场景 |
|---|---|---|
| 江湖书院 V2 | `/`、`frontend-v2/` | 默认入口；2.5D 团队/房间视图、问策、卷宗与完整设置 |
| 经典 Web 控制台 | `/v1/`、`frontend/` | 兼容入口；经典团队配置、聊天室、设置与用量管理 |
| TUI | `tui/` | 终端环境、远程服务器与轻量操作 |

### 基于 TSP 的工具层

工具执行层支持 [TSP（Tool Service Protocol）](https://github.com/alexazhou/TSP)，也保留原生 Function Calling 驱动。通过 `driver_fallback.tsp_to_native` 可以在外部 TSP/GTSP 不可用时回退到原生工具调用，避免单一工具驱动阻塞整个任务。

---

## v0.8.4 重点更新

- **SSRF 防护支持本地 LLM**：`safeHttpUtil` 新增 `allow_private` 参数，LLM 服务配置（添加/修改/测试/快速初始化/从厂商创建）全部允许 `localhost`、`127.0.0.1`、`192.168.x.x` 等私有/回环地址，用户可直连本地 Ollama / llama.cpp 等服务；Ghost 博客地址仍保持严格公网校验。
- **限流阈值大幅放宽**：全局限流 120 → 2000 次/分钟，LLM 测试 10 → 100，检查更新 5 → 100，解决反向代理（Nginx/Cloudflare）后 IP 坍缩导致正常使用被误杀的问题。
- **SSRF 错误信息中文化**：DNS 解析失败、非公共地址等错误改为中文提示并附带域名/IP 诊断信息，方便排查。
- **Ghost Key 保存修复**：`configUtil._save_setting_to_file` 的 Ghost 配置序列化从 `exclude_unset=True` 改为全量 `model_dump`，修复通过 API 属性赋值修改的 key 不被持久化的问题。
- **LLM 厂商预设更新**：`catalog.json` 更新为 2025-2026 最新模型（doubao-seed-1-6、Qwen3、GPT-4.1、Gemini 2.5、Claude 4 等）。
- 以下为 v0.8.3 起的核心能力（本版本一并包含）：

## v0.8.3 重点更新

- **LLM 服务管理修复**：内置服务标记 `index=-1`，前端用 `service.index`，彻底解决"服务序号越界"问题；配置 LLM 后自动重启调度器。
- **调度器优化**：OPERATOR 在 SCHEDULING 状态发消息时重置轮次触发新调度，修复服务重启后房间卡死、用户提问无响应的死锁问题；`include_failed=False` 避免旧 FAILED 任务阻塞。
- **实时消息修复**：WebSocket `normalizeEvent` 从 `gt_message` 提取字段；心跳保活 + 5 秒快速重连。
- **新讨论功能**：后端归档 Run + 清空消息，前端新会话模式。
- **六爻研究院**：10 位专家、4 个房间、3 层部门树、五层研判体系。
- **性能优化**：`default_room_max_rounds` 100→10，`max_concurrency` 5→20。
- **品牌清理**：移除所有 TogoSpace 引用，统一为 DigitalLife；莫比乌斯环图标；环境变量 `TOGOSPACE_*` → `DIGITALLIFE_*`。
- 以下为 v0.8.2 起的核心能力（本版本一并包含）：

## v0.8.2 重点更新

- **大模型预设全面更新**：厂商预设目录（`catalog.json`）更新为 2026 最新模型列表，新增智谱 GLM、Google Gemini、火山引擎 AgentPlan（`ark-code-latest`）；Kimi 接入地址更新为 `api.moonshot.ai`。
- **SSRF 校验修复**：放宽 `resolve_public_addresses` 为"存在公网 IP 即允许"（仅保留公网 IP 供 pinned resolver），修复手动添加大模型与 Ghost 博客地址被误杀为 non-public 的问题；纯内网域名仍被拒绝，SSRF 防护不降级。
- **LLM 多 Key 轮询**：`LlmServiceConfig` 新增 `api_keys` 字段，支持同一服务配置多个 Key 按轮询方式负载均衡，失败仍走兜底链。
- **特殊版本开箱即用**：release 构建时从 GitHub Secrets 注入内置默认凭据（LLM/搜索/Ghost）到 `builtin_keys.json`，产物自带配置，源码不暴露密钥。
- 以下为 v0.8.1 起的核心能力（本版本一并包含）：

## v0.8.1 重点更新

- **Ubuntu 原生安装包**：Release 新增 Linux `.deb` 与 AppImage 安装包（amd64 / arm64），`.deb` 可 `sudo apt install ./digitallife-*.deb` 安装，AppImage 下载后 `chmod +x` 即可运行；macOS 签名安装包与 Docker 多架构镜像同步产出。
- 以下为 v0.8.0 起的核心能力（本版本一并包含）：

### v0.8.0 起的核心更新

- **联网搜索与网页抓取修复**：`web_search` / `web_fetch` 支持 Tavily、Brave、Bing 三级引擎；新增专用搜索配置与**多 Key 轮询、失败自动切换下一个 Key/引擎**，网页抓取增加响应体大小上限防止内存耗尽。
- **大模型服务预设与兜底链**：后台新增常见服务商下拉预设（小米 MiMo、DeepSeek、火山方舟 AgentPlan / CodingPlan、Kimi、APINebula、自定义），选中即带默认接入地址与模型识别，只需填 API Key；支持配置多个模型、设置**默认首选模型**与**兜底模型链**——首选不可用时自动切换到下一个兜底服务。
- **Ghost 博客发布修复与自动化**：严格按 Ghost Admin API（JWT 鉴权 + `source=html`）实现，后台可配置博客地址、Content API Key、Admin API Key、发布状态；每个团队讨论完成后可**自动将完整汇总结论发布到博客，全文无截断**。
- **历史卷宗查看修复**：修复最终报告不落盘导致的“历史卷宗无法查看”，新增卷宗列表与详情页，历史结论可回看与下载；讨论完成后新增**「发起新话题」入口**，一键开启新一轮书院讨论。
- **各院专业技能**：为研究检索、写作文档、数据分析、代码工程、代码审查、合规审校、PPT/分镜/UI 设计、影视制作、市场调研、财务分析、政策起草、项目管理、内容运营等工作类型内置对口 Skills，并绑定到对应院/角色。
- **安全加固**：SSRF 防护（DNS Pinning + 逐跳重定向校验）、CSRF/安全响应头、Claude SDK 危险工具审批门（可配置严格模式）、LLM 密钥脱敏与日志降级、限流内存清理、登录时序防枚举、`cookie_secret` 持久化、上传路径沙箱复验、zip 炸弹真流式上限等；冲突项默认放行、可通过 `setting.security` 在生产开启严格模式。
- **并发与数据一致性修复**：轮次 Function Calling 总步数熔断、消费者/事件回调异常检索（避免 Agent 静默卡死）、Agent 历史写入原子性与事务级重试、Token 估算移出事件循环、超长上下文压缩收敛等。

> 完整变更见 [RELEASE_NOTES_v0.8.0.md](RELEASE_NOTES_v0.8.0.md)。

---

## 核心能力

### 多 Agent 自主协作

- Agent 在统一聊天室内自由交流、补充、质疑与辩论；
- 支持多房间、多部门、多层级团队树；
- 支持多团队并行运行，每个 Agent 或团队可选择不同模型；
- 支持顺序讨论、快速共识、并行观点等调度策略；
- 汇总角色可调用 `submit_conclusion` 形成结构化最终答案。

### 可配置 Agent 与团队

- 自定义角色名称、系统提示词、专业能力、人格风格与工具；
- 从预设创建团队，也可导出团队预设；
- 支持房间成员编排和部门树维护；
- 支持用户私有团队、公共预设与管理员管理能力。

### 运行进度与可观测性

- 任务级状态：排队、运行、完成、失败及百分比；
- 房间级状态：当前 Agent、活动、消息数、贡献者进度；
- Agent 活动：推理、回复、工具调用、上游重试等时间线；
- Token 用量：实时、汇总与总量统计；
- 最终答案和 Ghost 发布状态可独立查询。

### 工具与文件

- TSP / 原生 Function Calling 双驱动与自动降级；
- 支持 Skill 导入、查询与删除；
- 聊天文件上传、下载、预览和工作目录沙箱；
- 支持读取 DOCX/XLSX/PPTX/Markdown，并生成 Word、Excel、PowerPoint 与 Markdown 交付物；
- 房间内提供卷宗上传入口和可点击下载卡片；
- 可选搜索能力与自定义模型服务；
- GTSP 安装脚本支持受信任发布源和校验文件。

### 多模型与兼容接口

项目通过 LiteLLM 接入 OpenAI-compatible 服务，可配置 DeepSeek、通义千问、Kimi、OpenAI、Anthropic 等模型或自建网关。每个服务可单独设置：

- `base_url`、`api_key`、`model`；
- `max_concurrency` 与 `requests_per_minute`；
- 上下文窗口、输出预留与自动压缩阈值；
- 额外请求头和经过白名单校验的 provider 参数。

---

## 内置团队

仓库内置多个可以直接启用或二次修改的团队预设：

| 团队 | 主要角色/能力 | 典型任务 |
|---|---|---|
| 股票分析大师团队 | 价值、成长、技术、量化、宏观、风控与 CIO 汇总 | 公司研究、行业比较、风险清单、观点辩论 |
| 国学命理研究团队 | 四柱、紫微、梅花、经典考证与综合研判 | 传统文化研究与多流派观点整理 |
| 软件研发团队 | 产品、架构、开发、测试、运维与评审 | 需求拆解、技术方案、代码审查、上线计划 |
| 创意脑暴团队 | 多角色发散、质疑、筛选与总结 | 产品创意、营销主题、活动方案 |
| 顶级规划智库 | 战略、产业、政策、金融、技术与风险专家 | 区域/企业战略和复杂规划 |
| AI 视频创作工坊 | 导演、编剧、分镜、视觉、素材与运营 | 视频策划、脚本、分镜和制作方案 |
| OPC 产业平台社区 | 政策、园区、招商、孵化、数据与合规 | 园区/创新中心全生命周期规划 |

预设位于 `assets/preset/teams/`，角色模板位于 `assets/preset/role_templates/`。

---

## 系统架构

```text
┌────────────────────────────────────────────────────────────┐
│  Classic Web / Wuxia V2 / TUI                             │
└───────────────────────┬────────────────────────────────────┘
                        │ HTTP + WebSocket
┌───────────────────────▼────────────────────────────────────┐
│ Controller：路由、鉴权、参数校验、租户边界、速率限制       │
├────────────────────────────────────────────────────────────┤
│ Service：任务运行、房间调度、Agent、LLM、工具、Ghost 队列 │
├────────────────────────────────────────────────────────────┤
│ DAL：SQLite / peewee-async / 迁移 / 运行快照                │
├────────────────────────────────────────────────────────────┤
│ Model：团队、房间、Agent、消息、活动、Run、Publication     │
├────────────────────────────────────────────────────────────┤
│ Util：配置、路径、日志、序列化、LLM HTTP 客户端            │
└────────────────────────────────────────────────────────────┘
```

后端遵循单向依赖：

```text
controller → service → dal → model → util
```

### 主要技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.11+、Tornado、Pydantic、aiohttp、LiteLLM |
| 数据 | SQLite、peewee、peewee-async、aiosqlite |
| 经典前端 | Vue 3、TypeScript、Vite、Vitest |
| V2 前端 | Vue 3、Vue Router、markdown-it、霞鹜文楷、Vitest |
| TUI | Textual |
| 部署 | Docker、Docker Compose、Nginx、systemd、GitHub Actions |

---

## 快速开始

### 环境要求

| 组件 | 建议版本 | 用途 |
|---|---|---|
| Python | 3.11+ | 后端、测试和构建脚本 |
| Node.js | 20+ | 两套 Web 前端 |
| npm | 随 Node.js 安装 | 前端依赖和构建 |
| Git | 近期稳定版 | 获取源码 |
| Docker / Compose | 可选 | 容器部署 |

### 方式一：Docker Compose（推荐）

```bash
git clone https://github.com/suvlife/DigitalLife.git
cd DigitalLife
docker compose up -d --build
```

访问：

- 江湖书院 V2（默认）：`http://localhost:8080/`
- 经典控制台：`http://localhost:8080/v1/`
- 旧 V2 链接 `/v2/...` 会兼容重定向到新的根路径
- 健康检查：`http://localhost:8080/system/status.json`

查看日志或停止服务：

```bash
docker compose logs -f digitallife
docker compose down
```

运行数据保存在 Compose 卷 `digitallife-storage` 中。删除容器不会自动删除该卷；执行 `docker compose down -v` 会删除卷，请先确认已备份。

### 方式二：源码运行

```bash
git clone https://github.com/suvlife/DigitalLife.git
cd DigitalLife

python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

cd frontend && npm ci && cd ..
cd frontend-v2 && npm ci && cd ..
.venv/bin/python scripts/build_frontend.py

.venv/bin/python src/backend_main.py
```

默认访问 `http://127.0.0.1:8180/` 即进入江湖书院 V2；经典控制台位于 `http://127.0.0.1:8180/v1/`。旧 `/v2/...` 链接会保留路径与查询参数并重定向到 V2 根路由。

如需指定配置目录或端口：

```bash
.venv/bin/python src/backend_main.py --config-dir /path/to/config --port 8180
```

### 方式三：前后端分离开发

终端 1：

```bash
.venv/bin/python src/backend_main.py --port 8180
```

终端 2（经典前端）：

```bash
cd frontend
npm run dev
# http://localhost:8181/
```

终端 3（V2，可选）：

```bash
cd frontend-v2
npm run dev
# http://localhost:8182/
```

### TUI

```bash
.venv/bin/python tui/tui_main.py --base-url http://127.0.0.1:8180
# 或
./scripts/start_tui.sh --base-url http://127.0.0.1:8180
```

---

## 配置说明

应用配置由 `setting.json` 管理。源码模式下首次启动会在运行时配置目录生成配置；容器默认使用 `/storage/setting.json`。可以从模板开始：

```bash
cp assets/config_template.json /path/to/config/setting.json
```

### 最小 LLM 配置示例

```json
{
  "language": "zh-CN",
  "bind_host": "127.0.0.1",
  "bind_port": 8180,
  "default_llm_server": "qwen",
  "llm_services": [
    {
      "name": "qwen",
      "enable": true,
      "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
      "api_key": "YOUR_API_KEY_HERE",
      "type": "openai-compatible",
      "model": "qwen-plus",
      "max_concurrency": 5,
      "requests_per_minute": 0
    }
  ]
}
```

也可在默认的江湖书院 V2 设置页添加、测试、启用和切换 LLM 服务；经典控制台仍可从 `/v1/` 使用。

### 关键配置项

| 配置 | 默认值 | 说明 |
|---|---:|---|
| `language` | `zh-CN` | 界面与提示语言 |
| `bind_host` | `127.0.0.1` | 默认仅本机监听 |
| `bind_port` | `8180` | HTTP / WebSocket 端口 |
| `auth.enabled` | `false` | Bearer Token 鉴权开关 |
| `auth.token` | 空 | API 与 WebSocket 使用的共享令牌 |
| `default_llm_server` | `null` | 默认启用的 LLM 服务名称 |
| `llm_services[].max_concurrency` | `5` | 单服务最大并发请求数 |
| `llm_services[].requests_per_minute` | `0` | 单服务每分钟请求限制，`0` 表示不主动限流 |
| `driver_fallback.tsp_to_native` | `true` | TSP 不可用时回退原生工具调用 |
| `ghost.enabled` | `false` | Ghost 自动发布总开关 |
| `ghost.publish_status` | `published` | 发布为 `published` 或 `draft` |
| `ghost.max_retry_attempts` | `6` | 持久化发布任务最大尝试次数 |

### Bearer Token 鉴权

若要监听局域网或公网地址，请务必开启鉴权并配置反向代理：

```json
{
  "bind_host": "0.0.0.0",
  "auth": {
    "enabled": true,
    "token": "REPLACE_WITH_A_LONG_RANDOM_TOKEN"
  }
}
```

HTTP 请求使用：

```bash
curl -H "Authorization: Bearer REPLACE_WITH_A_LONG_RANDOM_TOKEN" \
  http://127.0.0.1:8180/teams/list.json
```

WebSocket 客户端连接后需要先发送认证消息；经典前端和 V2 前端会按配置完成该流程。

### 密钥管理

- 不要把真实密钥写进 Git 仓库、镜像层或截图；
- `.env`、`.env.*`、`*secrets*.json` 和本地密钥覆盖文件已被忽略；
- `assets/builtin_keys.example.json` 仅包含占位符；
- Ghost 支持 `GHOST_ENABLED`、`GHOST_API_URL`、`GHOST_ADMIN_API_KEY`、`GHOST_CONTENT_API_KEY`、`GHOST_AUTO_PUBLISH` 环境变量覆盖；
- 生产环境优先使用部署平台 Secret、私有 `setting.json` 或只读挂载。

---

## Web 界面与使用流程

### 首次使用

1. 启动后打开默认的江湖书院 V2；
2. 在设置页添加至少一个可用的 LLM 服务；
3. 启用一个内置团队或创建自己的团队；
4. 进入房间输入任务；
5. 观察 Agent 活动、工具调用、消息和 Token 使用；
6. 等待汇总角色提交最终结论；
7. 在 V2 运行页查看任务级、房间级进度与归档结果。

### 江湖书院 V2 `/`

默认入口，适合完整配置、问策和运行观察：

- 首页、团队院落与明确的主问策房间；
- 团队成员、部门树、研究室与团队默认模型配置；
- LLM 服务、角色模板、Skill、Ghost 与系统维护设置；
- 房间对话、文件交付、任务/房间进度与最终答案；
- 当前运行与按 Run 隔离的历史卷宗。

### 经典控制台 `/v1/`

经典控制台作为独立兼容应用保留，继续提供原有控制台工作流。旧 `/v2/...` 地址会保留路径与查询参数并重定向到新的 V2 根路径。

---

## API 与实时事件

所有 JSON API 与 WebSocket 复用同一后端端口。启用鉴权后，除少量健康检查/认证豁免端点外均需 Bearer Token。

### 常用 API

| 类别 | 方法与端点 | 说明 |
|---|---|---|
| 系统 | `GET /system/status.json` | 健康状态与基础信息 |
| 团队 | `GET /teams/list.json` | 团队列表 |
| 团队 | `GET /teams/{id}.json` | 团队详情 |
| 部门 | `GET /teams/{id}/dept_tree.json` | 部门树 |
| 房间 | `GET /rooms/{id}/messages/list.json` | 消息列表 |
| 房间 | `POST /rooms/{id}/messages/send.json` | 发送消息并触发任务 |
| 文件 | `POST /rooms/{id}/messages/upload.json` | 上传文件 |
| Run | `GET /runs/current.json?team_id={id}` | 当前运行快照 |
| Run | `GET /runs/list.json?team_id={id}` | 历史运行 |
| Run | `GET /runs/{id}.json` | 运行详情 |
| Run | `GET /runs/{id}/rooms.json` | 房间进度 |
| Run | `GET /runs/{id}/timeline.json` | 活动时间线 |
| Run | `GET /runs/{id}/final_answer.json` | 最终答案与博客状态 |
| 用量 | `GET /usage/realtime.json` | 实时 Token 用量 |
| 用量 | `GET /usage/summary.json` | 聚合用量 |
| 配置 | `GET /config/llm_services/list.json` | LLM 服务列表（密钥脱敏） |
| WebSocket | `WS /ws/events.json` | 消息与进度事件 |

### WebSocket

```js
const ws = new WebSocket("ws://127.0.0.1:8180/ws/events.json");
ws.addEventListener("open", () => {
  // 仅在 auth.enabled=true 时发送
  ws.send(JSON.stringify({ type: "auth", token: "YOUR_TOKEN" }));
});
ws.addEventListener("message", (event) => {
  console.log(JSON.parse(event.data));
});
```

前端已处理消息、Agent 活动、Run、Room Run、博客发布和连接状态等事件；自定义客户端应容忍新增事件字段。

---

## Ghost 博客发布

启用后，汇总角色提交最终结论时会创建持久化发布任务。发布 worker 会：

1. 生成标题、正文和标签；
2. 将 Markdown 转换为经过清理的 HTML；
3. 使用 Ghost Admin API 创建文章；
4. 通过 publication key 和内容哈希保证幂等；
5. 失败后按计划重试，并在应用重启后恢复；
6. 将发布状态、文章 ID 和 URL 写回 Run 快照并推送事件。

示例：

```json
{
  "ghost": {
    "enabled": true,
    "api_url": "https://blog.example.com",
    "admin_api_key": "YOUR_GHOST_ADMIN_API_KEY",
    "content_api_key": "",
    "auto_publish": true,
    "publish_status": "draft",
    "max_retry_attempts": 6
  }
}
```

> [!NOTE]
> 写入文章使用 **Ghost Admin API Key**；Content API Key 不能用于发布。建议先设置 `publish_status: "draft"` 验证格式，再切换到 `published`。

---

## 数据、安全与生产部署

### 数据目录与备份

- 源码运行：数据目录由应用路径策略和 `--config-dir` 决定；
- Docker：`/storage`，Compose 映射到 `digitallife-storage`；
- 主要内容包括 `setting.json`、SQLite 数据库、工作目录和运行日志；
- 数据库迁移在启动时按顺序执行；
- 更新前建议备份整个数据目录，或调用系统数据库备份能力。

### 已实现的安全措施

- 默认绑定 `127.0.0.1`；
- Bearer Token 常量时间比较；
- 多租户资源归属检查；
- LLM 测试接口 SSRF 防护；
- Skill 导入 Zip-Slip / Zip 炸弹防护；
- 文件类型、大小和路径限制；
- API 密钥脱敏和 Ghost 密钥不回传；
- 敏感接口的内存滑动窗口限流；
- LLM provider 参数白名单；
- Markdown 到 HTML 的链接和标签清理。

### 生产环境检查清单

- [ ] 使用 HTTPS 反向代理，不直接暴露 Tornado；
- [ ] `bind_host=0.0.0.0` 时启用 `auth.enabled` 并设置高强度随机 token；
- [ ] 将 API Key 放入 Secret 或私有配置，不写入仓库；
- [ ] 限制安全组/防火墙，只开放必要端口；
- [ ] 持久化并定期备份 `/storage`；
- [ ] 先在测试环境执行数据库迁移和版本升级；
- [ ] 根据供应商配额设置并发与 RPM；
- [ ] 为 Ghost 发布先使用草稿模式；
- [ ] 监控健康检查、应用日志、磁盘与模型费用。

### Linux 服务器部署

仓库包含 Nginx、systemd、Watchdog、自动更新和 SSL 相关脚本。完整命令和注意事项见 [`deploy/README.md`](deploy/README.md)。快速入口：

```bash
git clone https://github.com/suvlife/DigitalLife.git
cd DigitalLife
bash deploy/deploy.sh
```

更新并保留数据：

```bash
bash deploy/update.sh
```

部署脚本带有环境假设，执行前请阅读脚本并根据自己的域名、目录、用户和 TLS 方案调整。

---

## 开发、测试与发布

### 后端测试

```bash
# 默认：unit + integration，并行执行
./scripts/run_tests.sh

# 覆盖率
./scripts/run_tests.sh --cov

# 指定测试或串行调试
./scripts/run_tests.sh tests/unit
./scripts/run_tests.sh -k "test_name"
./scripts/run_tests.sh --serial
```

API 测试通常需要单独启动后端：

```bash
./scripts/run_tests.sh tests/api
```

### 前端测试与构建

```bash
cd frontend
npm ci
npm run test:run
npm run build

cd ../frontend-v2
npm ci
npm run test:run
npm run build
```

统一构建并同步静态资源：

```bash
.venv/bin/python scripts/build_frontend.py --install
# 仅验证构建、不复制到 assets：
.venv/bin/python scripts/build_frontend.py --no-sync
```

### 类型与版本检查

```bash
./scripts/run_mypy.sh
.venv/bin/python scripts/check_version_consistency.py
```

更新版本：

```bash
.venv/bin/python scripts/set_version.py 0.6.0
```

脚本会同步 `VERSION`、Python 版本、两套前端 `package.json`、Dockerfile 和 Compose 镜像版本。创建 `v*` 标签会触发 GitHub Actions 的 macOS Release 和多架构容器工作流；发布前应确认仓库 Secrets 已正确配置。

---

## 常见问题

<details>
<summary><strong>启动后提示没有可用的 LLM 服务</strong></summary>

在经典控制台设置页添加并启用服务，或编辑 `setting.json` 中的 `llm_services`；同时确保 `default_llm_server` 指向已启用服务。
</details>

<details>
<summary><strong>Docker 健康检查正常，但外部无法访问</strong></summary>

确认 `8080` 端口映射、防火墙和安全组；生产环境应通过 Nginx/Caddy/Traefik 提供 HTTPS。不要为了方便关闭鉴权。
</details>

<details>
<summary><strong>V2 页面刷新后 404</strong></summary>

生产构建由 Tornado 根路径 SPA fallback 处理；经典控制台固定在 `/v1/`，旧 `/v2/...` 由后端兼容重定向。使用外部反向代理时应将 `/`、`/v1/` 和 `/v2/` 均转发到后端。
</details>

<details>
<summary><strong>任务卡住或频繁出现 429</strong></summary>

根据模型供应商限制降低 `max_concurrency`，设置 `requests_per_minute`，检查活动时间线中的重试元数据，并避免多个团队共享同一个低配额 Key。
</details>

<details>
<summary><strong>Ghost 发布失败</strong></summary>

确认 URL 可从服务器访问、使用 Admin API Key、时间同步正常，并先调用连接测试。失败任务会持久化重试，状态可从 Run 最终答案接口和前端查看。
</details>

<details>
<summary><strong>如何安全更新</strong></summary>

先备份数据目录和数据库，再拉取新版本并运行测试/构建。服务器部署可使用 `deploy/update.sh`，不要删除持久化卷或覆盖私有配置。
</details>

<details>
<summary><strong>macOS 提示“无法验证开发者”或“应用已损坏”</strong></summary>

当前 GitHub Release 在仓库未配置 Apple Developer ID 证书时发布的是 **ad-hoc 完整性签名社区包**，不是 Apple 官方公证包。请不要直接拖动旧版 `.app`：

1. 下载名称以 `digitallife-` 开头的 ZIP；
2. 解压并双击 `安装数字人生.command`；
3. 若脚本被拦截，按住 Control 点击后选择“打开”，或在“系统设置 → 隐私与安全性”中允许；
4. 安装脚本会验证签名、移除下载隔离属性并安装到 `/Applications/DigitalLife.app`。

维护者配置 `APPLE_CERTIFICATE_P12`、`APPLE_CERTIFICATE_PASSWORD`、`APPLE_ID`、`APPLE_APP_PASSWORD`、`APPLE_TEAM_ID` 和 `APPLE_SIGNING_IDENTITY` 后，GitHub Actions 会自动生成 Developer ID 签名且完成 Apple 公证、Staple 的正式包。
</details>

---

## 项目结构

```text
DigitalLife/
├── src/
│   ├── controller/              # HTTP / WebSocket 控制器
│   ├── service/                 # Agent、Run、调度、LLM、Ghost 等业务服务
│   ├── dal/                     # 数据访问和数据库管理器
│   ├── model/                   # 核心模型与数据库模型
│   ├── util/                    # 配置、路径、日志、序列化、HTTP 客户端
│   ├── backend_main.py          # 后端入口
│   └── route.py                 # API 与双前端路由
├── frontend/                    # 经典 Vue 3 控制台
├── frontend-v2/                 # 江湖书院 V2（默认生产路径 /）
├── tui/                         # Textual 终端客户端
├── assets/
│   ├── migrate/                 # SQLite 迁移
│   ├── preset/                  # 团队与角色预设
│   ├── frontend/                # 经典前端构建输出（本地生成）
│   └── frontend-v2/             # V2 构建输出（本地生成）
├── tests/                       # unit / integration / api
├── scripts/                     # 构建、测试、版本、安装与发布工具
├── deploy/                      # Linux/Nginx/systemd 部署资源
├── docs/                        # 设计、版本和使用文档
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── VERSION
```

---

## 路线与已知边界

- V2 是默认入口，覆盖任务观察、团队导航、问策、卷宗、模型、成员、组织树与研究室设置；经典控制台作为 `/v1/` 兼容界面保留；
- Run API 当前以查询和恢复展示为主，取消、房间级重试等写操作仍可继续演进；
- 本地限流器是单进程内存实现，多实例生产部署应在网关层增加统一限流；
- SQLite 适合单机和中小规模部署，大规模多实例部署需要额外评估数据库与消息协调方案；
- 自动发布、自动更新和模型调用均属于外部副作用，生产环境应配合权限、审计、备份和费用告警。

---

## 贡献

欢迎提交 Issue 与 Pull Request。建议在提交前：

1. 阅读 [`CLAUDE.md`](CLAUDE.md) 中的架构与开发约定；
2. 保持 `controller → service → dal → model → util` 依赖方向；
3. 为新增行为补充测试；
4. 分别验证两套前端；
5. 不提交 API Key、用户数据、构建产物和本地运行目录。

---

## 许可证与致谢

仓库当前包含的前端许可证文本见 [`frontend/LICENSE`](frontend/LICENSE)，第三方字体许可见 [`frontend-v2/licenses/LXGW-WEN-KAI-NOTICE.md`](frontend-v2/licenses/LXGW-WEN-KAI-NOTICE.md)。在复用或分发代码前，请同时检查各目录和依赖的许可证要求。

感谢以下项目：

- [TSP（Tool Service Protocol）](https://github.com/alexazhou/TSP)
- [Tornado](https://www.tornadoweb.org/)
- [Vue.js](https://vuejs.org/)
- [LiteLLM](https://github.com/BerriAI/litellm)
- [Textual](https://textual.textualize.io/)
- [peewee-async](https://github.com/woodyl/peewee-async)
- [霞鹜文楷](https://github.com/lxgw/LxgwWenKai)

如果这个项目对你有帮助，欢迎 Star、Fork、提交反馈或分享你的团队预设。
