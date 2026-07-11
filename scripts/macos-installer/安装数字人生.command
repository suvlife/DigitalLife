#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_SOURCE="$(find "$SCRIPT_DIR" -maxdepth 1 -type d -name 'DigitalLife*.app' | head -1)"
APP_TARGET="/Applications/DigitalLife.app"

if [ -z "$APP_SOURCE" ]; then
  echo "未在安装包中找到 DigitalLife.app"
  read -r -p "按回车键退出…"
  exit 1
fi

echo "正在安装 DigitalLife 到 /Applications…"
# GitHub 下载的未公证社区构建会带 quarantine；在用户主动执行安装器后移除该属性。
xattr -dr com.apple.quarantine "$APP_SOURCE" 2>/dev/null || true
codesign --verify --deep --strict "$APP_SOURCE"
rm -rf "$APP_TARGET"
ditto "$APP_SOURCE" "$APP_TARGET"
xattr -dr com.apple.quarantine "$APP_TARGET" 2>/dev/null || true
codesign --verify --deep --strict "$APP_TARGET"

echo "安装完成，正在启动 DigitalLife…"
open "$APP_TARGET"
echo "如果系统仍弹出安全提示，请在 系统设置 → 隐私与安全性 中点击‘仍要打开’。"
read -r -p "按回车键关闭此窗口…"
