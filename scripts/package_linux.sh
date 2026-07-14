#!/usr/bin/env bash
# 将 PyInstaller onedir 产物（dist/digitallife/）打包为 .deb 与 AppImage。
# 由 CI (release.yml build-linux) 在 Ubuntu 上调用，也可本地运行。
#
# 用法： bash scripts/package_linux.sh <version> <arch>
#   version 例： 0.8.0     arch 例： amd64 | arm64
# 依赖： dpkg-deb（Ubuntu 自带）、wget（下载 appimagetool）、file
set -euo pipefail

VERSION="${1:?用法: package_linux.sh <version> <arch>}"
ARCH="${2:?用法: package_linux.sh <version> <arch>}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

DIST_APP="dist/digitallife"
[ -d "$DIST_APP" ] || { echo "❌ 未找到 $DIST_APP（请先用 digital_life_linux.spec 构建）"; exit 1; }

APPNAME="digitallife"
DISPLAY="数字人生 DigitalLife"
ICON_SRC="assets/icons/togo_status_64.png"

# ---- 通用 AppDir 结构 ---------------------------------------------------------
STAGE="dist/_linux_stage"
rm -rf "$STAGE"
APPDIR="$STAGE/AppDir"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/lib/$APPNAME" \
         "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/64x64/apps"

# 拷贝 onedir 到 /usr/lib/digitallife
cp -r "$DIST_APP/." "$APPDIR/usr/lib/$APPNAME/"

# 启动包装脚本（放 /usr/bin，指向内部可执行）
cat > "$APPDIR/usr/bin/$APPNAME" <<'WRAP'
#!/usr/bin/env bash
exec "/usr/lib/digitallife/digitallife" "$@"
WRAP
chmod +x "$APPDIR/usr/bin/$APPNAME"

# 图标
if [ -f "$ICON_SRC" ]; then
  cp "$ICON_SRC" "$APPDIR/usr/share/icons/hicolor/64x64/apps/$APPNAME.png"
  cp "$ICON_SRC" "$APPDIR/$APPNAME.png"
fi

# .desktop
cat > "$APPDIR/usr/share/applications/$APPNAME.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=$DISPLAY
Comment=Multi-agent collaboration platform
Exec=$APPNAME
Icon=$APPNAME
Terminal=true
Categories=Development;Utility;
DESK
cp "$APPDIR/usr/share/applications/$APPNAME.desktop" "$APPDIR/$APPNAME.desktop"

# ---- 1) 构建 .deb -------------------------------------------------------------
DEB_ARCH="$ARCH"   # amd64 / arm64 与 dpkg 架构名一致
DEB_ROOT="$STAGE/deb"
mkdir -p "$DEB_ROOT/DEBIAN" "$DEB_ROOT/usr"
cp -r "$APPDIR/usr/." "$DEB_ROOT/usr/"
INSTALLED_KB=$(du -sk "$DEB_ROOT/usr" | cut -f1)
cat > "$DEB_ROOT/DEBIAN/control" <<CTRL
Package: $APPNAME
Version: $VERSION
Section: utils
Priority: optional
Architecture: $DEB_ARCH
Installed-Size: $INSTALLED_KB
Maintainer: DigitalLife Team <noreply@guofeng.me>
Description: DigitalLife multi-agent collaboration platform
 A multi-agent collaboration platform where multiple LLM agents discuss,
 call tools, track progress and synthesize final answers.
CTRL
DEB_NAME="digitallife-${VERSION}-linux-${ARCH}.deb"
dpkg-deb --build --root-owner-group "$DEB_ROOT" "dist/$DEB_NAME"
echo "✅ 生成 dist/$DEB_NAME"

# ---- 2) 构建 AppImage ---------------------------------------------------------
# AppRun 指向内部可执行
cat > "$APPDIR/AppRun" <<'RUN'
#!/usr/bin/env bash
HERE="$(dirname "$(readlink -f "${0}")")"
exec "$HERE/usr/lib/digitallife/digitallife" "$@"
RUN
chmod +x "$APPDIR/AppRun"

# appimagetool 架构名
case "$ARCH" in
  amd64) AI_ARCH="x86_64" ;;
  arm64) AI_ARCH="aarch64" ;;
  *)     AI_ARCH="$ARCH" ;;
esac
AITOOL="dist/appimagetool-${AI_ARCH}.AppImage"
if [ ! -x "$AITOOL" ]; then
  wget -qO "$AITOOL" "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${AI_ARCH}.AppImage" || {
    echo "⚠️  下载 appimagetool 失败，跳过 AppImage（.deb 已生成）"; exit 0; }
  chmod +x "$AITOOL"
fi
APPIMAGE_NAME="digitallife-${VERSION}-linux-${ARCH}.AppImage"
# CI 容器内无 FUSE，用 --appimage-extract-and-run
ARCH="$AI_ARCH" "$AITOOL" --appimage-extract-and-run "$APPDIR" "dist/$APPIMAGE_NAME" || {
  echo "⚠️  AppImage 构建失败（.deb 已生成，可仅发布 .deb）"; exit 0; }
echo "✅ 生成 dist/$APPIMAGE_NAME"

# ---- 校验和 -------------------------------------------------------------------
( cd dist && for f in "$DEB_NAME" "$APPIMAGE_NAME"; do
    [ -f "$f" ] && sha256sum "$f" > "$f.sha256"; done )
echo "✅ Linux 打包完成"
