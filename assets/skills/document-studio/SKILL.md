---
name: document-studio
description: 读取与生成 Word、Markdown 和结构化文档，要求产物可下载、版式规范并经过内容检查。
---
# 文档制作技能

## 适用范围
- 读取 `.doc`、`.docx`、`.md`、`.markdown`、`.txt` 文件并提炼结构与正文。
- 生成 Word (`.docx`) 与 Markdown (`.md`) 交付物。
- 将房间讨论、研究结论、表格及引用整理成正式文档。

## 工作流程
1. 先从团队工作目录的 `uploads/` 读取用户上传文件；不要猜测文件内容。
2. Word 读取优先使用 `python-docx`，旧 `.doc` 可使用 LibreOffice/系统转换工具转成 `.docx` 后读取。
3. Word 生成使用 `python-docx`：设置标题层级、正文、列表、表格、页眉页脚和页码；中文正文优先使用霞鹜文楷或可用中文字体。
4. Markdown 生成必须包含清楚的标题层级、列表、表格和结论区。
5. 产物统一写入团队工作目录的 `outputs/`，文件名使用中文主题加时间戳，避免覆盖。
6. 写完后重新打开文件检查段落数、表格数和关键文字，确认文件可读。
7. 在回复中给出相对路径，例如 `outputs/项目方案.docx`，供网站识别并提供下载。

## 依赖
可使用 `python-docx`、`markdown-it-py`、LibreOffice（若部署环境提供）。若依赖不可用，应明确说明并输出 Markdown 作为可靠降级产物。
