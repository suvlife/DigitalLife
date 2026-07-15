# -*- mode: python ; coding: utf-8 -*-
"""Windows PyInstaller spec - 产出 onedir 应用，打包为 zip 便携版。

与 Linux 版的区别：
- 入口用 windows_launcher.py；
- 排除 macOS/Linux 专用隐藏导入和 gtsp 平台可执行文件；
- console=True 保持命令行可见，方便排查启动问题。
"""
import os
import re
import fnmatch

REPO_ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

_ver_src = open(os.path.join(REPO_ROOT, "src", "version.py")).read()
APP_VERSION = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', _ver_src).group(1)
print(f"ℹ️  windows build, version: {APP_VERSION}")

import litellm
LITELLM_PATH = os.path.dirname(litellm.__file__)

import certifi
CERTIFI_PATH = os.path.dirname(certifi.__file__)

a = Analysis(
    [os.path.join(REPO_ROOT, "scripts", "windows_launcher.py")],
    pathex=[os.path.join(REPO_ROOT, "src")],
    binaries=[],
    datas=[
        (os.path.join(REPO_ROOT, "assets"), "assets"),
        (LITELLM_PATH, "litellm"),
        (CERTIFI_PATH, "certifi"),
    ],
    hiddenimports=[
        "tornado",
        "tornado.platform.asyncio",
        "tornado.routing",
        "tornado.httputil",
        "pydantic",
        "pydantic_core",
        "aiosqlite",
        "aiosqlite.core",
        "peewee",
        "peewee_async",
        "PIL",
        "PIL.Image",
        "PIL.ImageDraw",
        "pytspclient",
        "tiktoken_ext",
        "tiktoken_ext.openai_public",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[
        os.path.join(SPECPATH, "rthook_tiktoken.py"),
    ],
    excludes=["textual", "mypy", "AppKit", "Foundation", "objc", "PyObjCTools"],
    noarchive=False,
)

EXCLUDE_PATTERNS = [
    "litellm/proxy/_experimental/out",
    "litellm/proxy/guardrails",
    "litellm/proxy/swagger",
    "litellm/integrations",
    "litellm/llms/huggingface",
    "_tcl_data",
    "_tk_data",
    "tcl8",
    # 只保留 Windows 版 gtsp，排除其它平台可执行文件
    "gtsp-macos-*",
    "gtsp-darwin-*",
    "gtsp-linux-*",
]

filtered_datas = []
for item in a.datas:
    dest_path = item[0]
    src_path = item[1]
    excluded = False
    for pattern in EXCLUDE_PATTERNS:
        if pattern in dest_path or fnmatch.fnmatch(os.path.basename(src_path), pattern):
            excluded = True
            break
    if not excluded:
        filtered_datas.append(item)
a.datas = filtered_datas

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="digitallife",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="digitallife",
)
