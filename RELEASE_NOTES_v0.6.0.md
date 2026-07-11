# digitallife v0.6.0 — 国风协作体验、Office 文档能力与稳定实时连接

`v0.6.0` 聚焦江湖书院 V2 的可读性、真实任务进度、文件与文档交付，以及 macOS/Linux 的可靠发布部署。

## 主要更新

### 江湖书院房间体验

- 全面中文化大师名称、身份标签、活动和任务状态，不再向用户暴露 `synthesizer`、`agent_state`、`compact` 等内部术语；
- 重新设计“本室问道卷”和“堂内动静”，使用国风叙事描述当前议题、思考、排盘、发言和完成状态；
- 修复长对话被挤成逐字竖排的问题，扩大讨论区并优化 Markdown、表格、代码块和响应式布局；
- 新增横向“发言次序”时间轴，点击人物或时间点可平滑跳转到对应对话并高亮；
- 房间名下展示所有参与大师与当前执言者。

### 真实进度与实时连接

- 房间进度按实际完成发言的大师人数与结构化任务比例计算；同一大师多次发言不再重复计数；
- 完成、失败和跳过的房间统一显示 100%，合议阶段显示 92%；
- WebSocket 后端改用有界顺序发送队列，避免活动事件洪峰创建无限异步任务；
- 重连采用稳定窗口和指数退避，鉴权失败停止无意义重试；
- 重连成功后自动重新拉取房间、任务、消息、活动和 Run 快照，避免断线期间状态永久缺失。

### Word、Excel、PPT 与 Markdown

- V2 房间支持上传 Word、PowerPoint、Excel、Markdown、PDF、CSV 和文本文件；
- 新增 `extract_office_file`，可读取 DOCX、XLSX、PPTX、Markdown、CSV、JSON 和文本；
- 新增 `generate_office_file`，可生成 DOCX、XLSX、PPTX 和 Markdown 并写入团队 `outputs/`；
- 内置 `document-studio`、`spreadsheet-studio` 和 `guizang-ppt-skill` 技能；
- 上传和生成的卷宗可在房间消息中直接下载。

### 霞鹜文楷与品牌统一

- 经典控制台和江湖书院 V2 均默认使用本地打包的霞鹜文楷，不依赖 CDN 或系统字体；
- macOS 应用、ZIP、Docker 镜像、Compose 服务、运行目录和 CI 发布名称统一为 `digitallife` / `DigitalLife`；
- 新桌面数据目录为 `~/.digitallife`，继续兼容旧版 `~/.togospace`；
- 更新检查指向 `suvlife/DigitalLife`。

### macOS 安装改进

- 应用构建后执行 ad-hoc 完整性签名并严格验证 bundle；
- 社区 ZIP 内附“安装数字人生.command”，负责校验签名、移除 GitHub 下载隔离属性并安装到 `/Applications/DigitalLife.app`；
- Release 工作流已支持 Apple Developer ID 签名与公证：配置证书和 Apple 公证 Secrets 后会自动生成正式公证包；
- 当前仓库没有配置 Apple Developer ID 证书，因此本次资产是社区签名包，不冒充 Apple 官方公证包。请解压后运行中文安装脚本。

## 安装与升级

### macOS

1. 下载 `digitallife-0.6.0-macos-arm64.zip`；
2. 解压后双击 `安装数字人生.command`；
3. 若 macOS 首次阻止脚本，请按住 Control 点击脚本并选择“打开”，或前往“系统设置 → 隐私与安全性”允许；
4. 安装器会安装到 `/Applications/DigitalLife.app` 并启动。

### Docker / Linux

升级前备份配置和数据库，然后重新拉取镜像或源码并构建两套前端。旧部署使用 `deploy/update.sh` 可保留 `/opt/digitallife-data`。

## 验证

- 后端 unit：560 passed，1 skipped；
- 经典前端：24 个测试文件、138 项测试通过，生产构建通过；
- V2：5 个测试文件、11 项测试通过，生产构建通过；
- Office 文档生成与重新读取测试通过；
- 浏览器验证霞鹜文楷已加载、房间时间轴可跳转、讨论区宽度和横排正常；
- 版本一致性、Python 编译和 `git diff --check` 通过。
