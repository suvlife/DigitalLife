# digitallife v0.8.1

在 v0.8.0 基础上，新增 **Ubuntu 原生安装包**，并让发布流程一次性产出 macOS、Ubuntu、Docker 三种平台产物。

## 新增

- **Ubuntu 原生可安装包**：Release 现同时提供 Linux **`.deb`** 与 **AppImage**（amd64 / arm64）。
  - `.deb`：`sudo apt install ./digitallife-0.8.1-linux-<arch>.deb`
  - AppImage：下载后 `chmod +x digitallife-0.8.1-linux-<arch>.AppImage && ./digitallife-...AppImage`
  - 均为「启动后端 + 自动打开浏览器」形态，无需 Docker。
- 发布 CI 新增 `build-linux` job（amd64 + arm64），与 macOS 签名包、Docker 多架构镜像在同一次 tag 推送中一并构建并挂载到 Release。

## 说明

- v0.8.0 的全部功能与修复（搜索多 key 轮询、LLM 预设+兜底、Ghost 自动发布、卷宗、各院技能、安全与并发修复）均包含在本版本中，详见 [RELEASE_NOTES_v0.8.0.md](RELEASE_NOTES_v0.8.0.md)。

---

Adds **native Ubuntu installers** on top of v0.8.0, so a single tag push now produces macOS, Ubuntu, and Docker artifacts.

- Release now ships Linux **`.deb`** and **AppImage** builds (amd64 / arm64) alongside the signed macOS package and multi-arch Docker image.
  - `.deb`: `sudo apt install ./digitallife-0.8.1-linux-<arch>.deb`
  - AppImage: `chmod +x` then run.
  - Both launch the backend and open the browser — no Docker required.
- CI gains a `build-linux` job (amd64 + arm64) that builds and attaches the Linux assets to the same release.

All v0.8.0 features and fixes are included; see the v0.8.0 notes for details.

**Full Changelog**: https://github.com/suvlife/DigitalLife/compare/v0.8.0...v0.8.1
