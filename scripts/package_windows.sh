#!/usr/bin/env bash
# Package Windows portable zip from PyInstaller onedir output.
# Usage: bash scripts/package_windows.sh <version>
set -euo pipefail

VERSION="${1:?Usage: package_windows.sh <version>}"
DIST_DIR="dist"
PKG_NAME="digitallife-${VERSION}-windows-amd64"
PKG_DIR="${DIST_DIR}/${PKG_NAME}"
ZIP_PATH="${DIST_DIR}/${PKG_NAME}.zip"

# PyInstaller COLLECT 产物目录
ONEDIR="${DIST_DIR}/digitallife"

if [ ! -d "${ONEDIR}" ]; then
  echo "ERROR: PyInstaller output not found: ${ONEDIR}"
  exit 1
fi

echo "==> Packaging ${PKG_NAME}"

# 复制 onedir 到打包目录
rm -rf "${PKG_DIR}"
cp -r "${ONEDIR}" "${PKG_DIR}"

# 创建启动批处理脚本
cat > "${PKG_DIR}/启动数字人生.bat" << 'BEOF'
@echo off
cd /d "%~dp0"
digitallife.exe
pause
BEOF

# 创建 README
cat > "${PKG_DIR}/README.txt" << 'EOF'
数字人生 (DigitalLife) v'"${VERSION}"'
========================================

快速开始：
1. 双击「启动数字人生.bat」
2. 等待 2-3 秒后浏览器自动打开
3. 如未自动打开，请手动访问 http://127.0.0.1:8180
4. 首次使用请在设置页面配置大模型服务
5. 按 Ctrl+C 退出

系统要求：
- Windows 10/11 (64位)
- 需要网络连接访问大模型 API

文档：https://github.com/suvlife/DigitalLife
EOF

# 打 zip
cd "${DIST_DIR}"
rm -f "$(basename "${ZIP_PATH}")"
powershell.exe -NoProfile -Command "Compress-Archive -Path '${PKG_NAME}' -DestinationPath '$(basename "${ZIP_PATH}")' -Force"
cd ..

# 生成 sha256
if command -v sha256sum &>/dev/null; then
  sha256sum "${ZIP_PATH}" > "${ZIP_PATH}.sha256"
elif command -v shasum &>/dev/null; then
  shasum -a 256 "${ZIP_PATH}" > "${ZIP_PATH}.sha256"
fi

echo "==> Done: ${ZIP_PATH}"
