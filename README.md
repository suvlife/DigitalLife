![数字人生](image/togo_agent_team.png)

# 数字人生 🚀

[English](README_EN.md) | [中文](README.md)

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Framework](https://img.shields.io/badge/framework-Tornado-orange.svg)](https://www.tornadoweb.org/)
[![UI](https://img.shields.io/badge/UI-Vue3%20%2B%20Textual-green.svg)](https://textual.textualize.io/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)](#)

**数字人生** 是一款专为大语言模型（LLM）设计的**多智能体协作开源软件**。让多个 AI Agent 能够像人类团队一样自由交流、实时协作、辩论博弈，共同攻克复杂任务。

> **关于名字的由来**：数字人生，寓意在数字世界中构建一个由 AI Agent 组成的"人生"团队，每个 Agent 都有自己独特的专业领域、人格风格和思辨能力，它们在团队中各司其职、相互启发、辩论博弈，最终产出超越单一 AI 的综合智慧。

### 基于 TSP 构建

数字人生的工具执行层基于 [TSP (Tool Service Protocol)](https://github.com/alexazhou/TSP) 构建 —— 一个轻量级的 LLM 工具服务器协议。借助 TSP，你可以用 **10 行代码构建自己的 Agent 工具**。

---

## ✨ 核心特性

### 1. 真正的团队协作
多 Agent 在统一的群聊空间内自由发言、互相启发、补位配合，模拟真实人类团队的沟通模式，通过协作产生 1+1>2 的效果。

### 2. 自由定义的 Agent 人格
你可以随心所欲地定义每个 Agent 的角色定位、专业技能与性格色彩。无论是严谨的代码审查专家，还是充满创意的产品策划，都能在你的定制下跃然纸上，打造专属的 AI 梦之队。

### 3. 辩论博弈与综合结论
多流派大师在辩论厅中各抒己见、相互驳斥，最终由综合研判角色调用 `submit_conclusion` 提交统一结论。支持多轮辩论博弈，确保结论经过充分论证。

### 4. 告别繁琐的工作流编排
无需事先规划死板的流程图。得益于强大的调度逻辑，Agent 们能根据当前任务进展自主决定"下一步该谁上"，广泛适用于各种突发、多变的复杂任务场景。

### 5. 强大的多层级团队架构
支持多部门、多层级的组织架构管理。你可以像管理真实公司一样划分部门（Dept），应对海量 Agent 参与的超大型复杂工程任务。

### 6. 全程可视化的友好体验
配备现代化的 Web 前端（Vue 3 + TypeScript），从团队角色配置到 Agent 的每一个思考步骤、每一条消息流向，全部实时可视化呈现。支持**浅色/深色/跟随系统**三种主题切换。

### 7. Token 用量实时统计
窗口右下角悬浮统计栏实时显示 Token 消耗量和当前模型信息，支持按 Agent / 模型 / 日期维度查看详细统计。

### 8. 文件上传与预览
聊天窗口支持文件上传（txt/md/json/csv/pdf/docx/xlsx/图片等格式），上传后 Agent 可通过工具读取文件内容，生成的文件支持点击下载和窗口预览。

### 9. 多团队多模型并行
支持多个团队同时进行独立任务，每个团队可选择不同的 LLM 模型（如团队A用 DeepSeek，团队B用 Qwen），避免多任务共用一个模型触发频率限制。

### 10. 极致的跨平台兼容性
基于 Python 与现代前端技术构建，完美支持 macOS、Windows 与 Linux 操作系统。提供 Docker 一键部署。

---

## 🏆 内置专业团队

### 股票分析大师团队（20 位 Agent）
汇聚全球顶级投资大师，覆盖四大投资流派：

| 流派 | 大师 | 核心理论 |
|------|------|---------|
| 价值投资 | 巴菲特、格雷厄姆 | 护城河/安全边际/内在价值 |
| 成长投资 | 费雪、彼得·林奇、欧尼尔 | 闲聊法/十倍股/CAN SLIM |
| 技术交易 | 威科夫、江恩、利弗莫尔、舒华兹 | 量价分析/时间周期/趋势追踪 |
| 量化宏观 | 西蒙斯、达里奥、索罗斯 | 统计套利/经济周期/反身性理论 |

另有道氏理论家、艾略特波浪大师、量价分析师、风控官、市场情报员、数据分析师等专业角色，大师们在"大师辩论厅"中辩论博弈，由首席投资官综合研判后提交结论。

### 国学命理研究团队（9 位 Agent）
融合中华传统命理学三大流派：

| 流派 | 大师 | 核心理论 |
|------|------|---------|
| 四柱八字 | 子平格局派、滴天髓派、盲派 | 渊海子平/五行气理/盲派口诀 |
| 紫微斗数 | 紫微大师 | 十四主星/四化飞星/大限流年 |
| 梅花易数 | 梅花大师 | 邵雍梅花/体用生克/万物类象 |

另有四柱排盘师、运势分析师、经典考证官、综合研判官，支持事业/财运/健康/爱情/家庭/学业等全领域预测。

### 软件研发团队 & 创意脑暴团队
内置标准软件开发团队（项目经理/架构师/前端工程师/后端工程师/测试工程师等）和创意脑暴团队（主持人/创意达人/魔鬼代言人/研究员等），开箱即用。

### 顶级规划智库（23 位专家）
覆盖全链条规划能力的综合智库团队：

| 部门 | 专家 | 职能 |
|------|------|------|
| 战略决策委员会 | 总规划师、麦肯锡咨询顾问 | 顶层规划、结构化分析、综合决策 |
| 政策研究组 | 政策研究/政策申报/政府事务专家 | 政府政策搜集、项目申报、汇报材料 |
| 产业研究组 | 产业研究/智算中心/大模型专家 | 产业链分析、算力规划、LLM选型 |
| 技术架构组 | 架构师/产品经理/前后端/测试 | 系统设计、产品规划、开发测试 |
| 财务法务组 | 财务/税务/法务专家 | 财务模型测算、税务规划、合规审查 |
| 商务运营组 | 售前/交付/销售/生态专家 | 解决方案、项目交付、市场拓展 |
| 文档支撑组 | 文档制作/AI内容/人力专家 | Word/PPT/Excel生成、内容运营 |

### AI视频创作工坊（12 位专家）
以导演制为核心的视频创作团队：

| 部门 | 专家 | 风格 |
|------|------|------|
| 导演组 | 纪录片导演、广告导演、科技科普导演、短视频导演 | 4种风格导演创意PK，辩论最佳方案 |
| 剧本组 | 首席编剧、分镜设计师 | 剧本结构、镜头语言、视觉叙事 |
| 视觉组 | 视觉设计总监、AI视频专家、AI图像专家 | Seedance 2.0视频 + Seedream图片生成 |
| 运营组 | 素材采集专家、商业叙事专家 | 素材管理、商业模式讲故事 |

4位导演就同一主题各出方案相互辩论，总导演综合裁决后提交最终创作方案。深度集成火山引擎产品编排能力。

### OPC产业平台社区（18 位专家）
火山引擎方视角的产业园区/创新中心全链路规划运营团队：

| 部门 | 专家 | 职能 |
|------|------|------|
| OPC总指挥部 | OPC总指挥、战略规划总监 | 火山引擎方首席代表、统筹全局、政府对接 |
| 政策规划组 | 政企合作/政策设计/产业基金专家 | 合作框架、政策体系、引导基金 |
| 园区规划组 | 园区规划/技术赋能/数字化架构师 | 空间规划、火山引擎技术输出、智慧园区 |
| 招商运营组 | 招商总监/生态合作/企业服务专家 | 招商引资、产业链整合、企业全生命周期服务 |
| 产业孵化组 | 孵化运营/投后管理/品牌营销专家 | 创业孵化、投后赋能、品牌建设 |
| 数据运营组 | 数据分析/活动运营/商业化/合规风控专家 | 数据驱动、活动运营、变现模式、风控 |

覆盖规划→建设→运营→发展全生命周期，政策组vs招商组辩论优惠力度vs可持续性。

---

## 🚀 快速开始

### 方法 1：Docker 一键部署（推荐）

```bash
# 克隆仓库
git clone https://github.com/suvlife/DigitalLife.git
cd DigitalLife

# 构建并启动
docker-compose up -d

# 访问 http://localhost:8080
```

### 方法 2：源码运行

```bash
# 克隆仓库
git clone https://github.com/suvlife/DigitalLife.git
cd DigitalLife

# 安装后端依赖
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 构建前端（需要 Node.js 20+）
cd frontend && npm install && npm run build && cd ..
mkdir -p assets/frontend && cp -r frontend/dist/* assets/frontend/

# 启动后端
.venv/bin/python src/backend_main.py

# 访问 http://127.0.0.1:8180
```

### 方法 3：开发模式（前后端分离）

```bash
# 终端 1：启动后端
.venv/bin/python src/backend_main.py --port 8180

# 终端 2：启动前端开发服务器
cd frontend && npm run dev
# 访问 http://localhost:8181（自动代理到后端）
```

### 首次配置
1. 打开 Web 界面，进入设置页
2. 在"LLM 服务"中添加你的 API Key（支持 Kimi/DeepSeek/通义千问/OpenAI/Anthropic 等）
3. 启用团队，开始使用

---

## 📁 项目结构

```
DigitalLife/
├── src/                        # 后端源码（Python + Tornado）
│   ├── backend_main.py         # 后端入口
│   ├── route.py                # API 路由
│   ├── controller/             # 控制器层（HTTP/WebSocket）
│   ├── service/                # 业务逻辑层
│   │   ├── agentService/       # Agent 核心引擎
│   │   ├── roomService/        # 聊天室与调度
│   │   ├── llmService/         # LLM 推理服务
│   │   ├── funcToolService/    # Agent 工具系统
│   │   └── ...
│   ├── dal/                    # 数据访问层（peewee-async）
│   ├── model/                  # 数据模型
│   └── util/                   # 工具类
├── frontend/                   # 前端源码（Vue 3 + TypeScript + Vite）
│   ├── src/
│   │   ├── components/         # Vue 组件
│   │   ├── pages/              # 路由页面
│   │   ├── realtime/           # WebSocket 实时层
│   │   ├── theme/              # 主题系统（深浅色）
│   │   └── ...
│   └── package.json
├── assets/                     # 静态资源
│   ├── preset/                 # 预置团队和角色模板
│   │   ├── teams/              # 团队配置 JSON
│   │   └── role_templates/     # 角色模板 JSON（56 个）
│   ├── frontend/               # 前端构建产物
│   ├── i18n/                   # 国际化文件
│   └── skills/                 # 内置技能
├── tests/                      # 测试套件（525 单元测试）
├── Dockerfile                  # Docker 构建
├── docker-compose.yml          # Docker Compose
└── requirements.txt            # Python 依赖
```

---

## 🔧 技术栈

### 后端
- **Python 3.10+** + **Tornado 6.5**（异步 Web 框架）
- **peewee + peewee-async + aiosqlite**（异步 ORM + SQLite）
- **LiteLLM**（多厂商 LLM 统一调用）
- **claude-agent-sdk**（Claude SDK 驱动）
- **pytspclient**（TSP 工具协议客户端）

### 前端
- **Vue 3.5** + **TypeScript 5.7** + **Vite 6**
- **vue-router 4** + **vue-i18n 9**
- **markdown-it** + **highlight.js**（Markdown 渲染）
- 原生 fetch（无 axios 依赖）
- 模块级 ref 单例 store（无 Pinia 依赖）

### 部署
- **Docker** + **Docker Compose**
- 非 root 用户运行
- SQLite WAL 模式 + 连接池

---

## 🛡️ 安全特性

- 默认仅监听 127.0.0.1（需外部访问时显式配置 + 启用鉴权）
- Bearer Token 鉴权（常量时间比较，防时序攻击）
- SSRF 防护（LLM 服务测试接口屏蔽内网/元数据端点）
- Zip-Slip + Zip 炸弹防护（Skill 导入）
- 文件上传白名单 + 大小限制
- 路径穿越防护（工作目录沙箱）
- API 密钥脱敏（不返回明文）
- 速率限制（敏感接口）
- provider_params 白名单过滤

---

## 📊 API 概览

| 类别 | 端点 | 说明 |
|------|------|------|
| 系统 | `GET /system/status.json` | 系统状态 |
| 团队 | `GET /teams/list.json` | 团队列表 |
| Agent | `POST /agents/{id}/modify_properties.json` | 修改 Agent 属性（含模型） |
| 房间 | `POST /rooms/{id}/messages/send.json` | 发送消息 |
| 房间 | `POST /rooms/{id}/messages/upload.json` | 上传文件 |
| 文件 | `GET /files/download.json` | 下载文件 |
| 文件 | `GET /files/preview.json` | 预览文件 |
| 用量 | `GET /usage/realtime.json` | 实时 Token 统计 |
| 用量 | `GET /usage/summary.json` | Token 统计面板 |
| LLM | `GET /config/llm_services/list.json` | LLM 服务列表 |
| WebSocket | `WS /ws/events.json` | 实时事件推送 |

---

## 🧪 测试

```bash
# 后端单元测试
.venv/bin/python -m pytest tests/unit -v

# 前端类型检查
cd frontend && npx vue-tsc --noEmit

# 前端构建
cd frontend && npm run build
```

---

## 📝 License

本项目基于开源协议发布，详见 [LICENSE](LICENSE)。

---

## 🙏 致谢

- [TSP (Tool Service Protocol)](https://github.com/alexazhou/TSP) — 工具执行层协议
- [Tornado](https://www.tornadoweb.org/) — 异步 Web 框架
- [Vue.js](https://vuejs.org/) — 渐进式前端框架
- [LiteLLM](https://github.com/BerriAI/litellm) — 多厂商 LLM 统一调用
- [peewee-async](https://github.com/woodyl/peewee-async) — 异步 ORM

---

## 📖 使用指南

### 首次使用
1. 打开网站，注册第一个账号（自动成为管理员）
2. 系统内置 LLM API Key，开箱即用无需配置
3. 在团队列表中启用需要的团队
4. 进入房间，向 Agent 发送消息开始对话

### 团队使用
- **股票分析大师团队**：在"大师辩论厅"提问个股分析，各流派大师辩论后由 CIO 调用 `submit_conclusion` 提交综合结论
- **国学命理团队**：在"排盘请求室"提供生辰八字，排盘师排盘后各流派大师分析，综合研判官提交结论
- **顶级规划智库**：在"战略指挥部"提出规划需求，各领域专家协作产出方案
- **AI视频创作工坊**：在"创作大本营"提出视频需求，4位导演辩论后总导演提交创作方案
- **OPC产业平台社区**：在"OPC作战室"提出产业园区规划需求，全链路专家协作

### 博客自动发布
- 综合研判官/CIO 调用 `submit_conclusion` 时，自动将完整分析发布到 Ghost 博客
- 博客内容包含：任务背景 + 各专家分析 + 综合结论
- 自动生成标题、标签（根据内容关键词）
- 博客格式：Ghost Lexical（完整渲染标题/段落/列表/粗体）

### 多租户
- 每个用户有自己的团队空间（私有团队）
- 公共预设团队所有用户可见
- 管理员可跨租户访问所有团队
- 用户可添加自己的 LLM API Key 覆盖内置 Key

### 搜索引擎
三级自动回退：Tavily（质量最好）> Brave > Bing（无需 Key）
搜索时自动加入当前年份，默认搜索过去一年的结果。

### 主题与字体
- 浅色/深色/跟随系统三种主题
- 默认苹方字体（PingFang SC），回退到 Microsoft YaHei / Noto Sans SC

### 移动端
- 支持 iOS/Android 浏览器访问
- 触控目标 44px（Apple HIG 标准）
- viewport-fit=cover 安全区适配

---

## 🚀 服务器部署

### 一键部署
```bash
git clone https://github.com/suvlife/DigitalLife.git
cd DigitalLife
bash deploy/deploy.sh
```

### 安全更新（保留数据）
```bash
cd /opt/digitallife
bash deploy/update.sh
```

### 自动化运维
- **systemd**：服务崩溃自动重启
- **Watchdog**：每 2 分钟健康检查（`deploy/watchdog.sh`）
- **Certbot**：SSL 证书自动续期
- **自动更新**：每天凌晨拉取新代码（`deploy/auto-update.sh`）
