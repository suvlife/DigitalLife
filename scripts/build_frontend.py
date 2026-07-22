#!/usr/bin/env python3
"""构建并同步 DigitalLife 的旧版、V2 与 V3 Web 前端。"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))


@dataclass(frozen=True)
class FrontendTarget:
    name: str
    source_dir: str
    asset_dir: str

    @property
    def dist_dir(self) -> str:
        return os.path.join(self.source_dir, "dist")


TARGETS = {
    "legacy": FrontendTarget(
        name="旧版前端",
        source_dir=os.path.join(REPO_ROOT, "frontend"),
        asset_dir=os.path.join(REPO_ROOT, "assets", "frontend"),
    ),
    "v2": FrontendTarget(
        name="V2 武侠前端",
        source_dir=os.path.join(REPO_ROOT, "frontend-v2"),
        asset_dir=os.path.join(REPO_ROOT, "assets", "frontend-v2"),
    ),
    "v3": FrontendTarget(
        name="V3 科幻全息前端",
        source_dir=os.path.join(REPO_ROOT, "frontend-v3"),
        asset_dir=os.path.join(REPO_ROOT, "assets", "frontend-v3"),
    ),
}


def _run(cmd: list[str], cwd: str) -> None:
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def _validate_target(target: FrontendTarget) -> None:
    package_json = os.path.join(target.source_dir, "package.json")
    if not os.path.isfile(package_json):
        raise SystemExit(f"❌ {target.name} 尚未初始化：{package_json} 不存在")


def _install(target: FrontendTarget) -> None:
    lock_file = os.path.join(target.source_dir, "package-lock.json")
    command = ["npm", "ci"] if os.path.isfile(lock_file) else ["npm", "install"]
    print(f"\n--- {target.name}: 安装依赖 ---")
    _run(command, target.source_dir)


def _build(target: FrontendTarget) -> None:
    print(f"\n--- {target.name}: npm run build ---")
    _run(["npm", "run", "build"], target.source_dir)
    if not os.path.isdir(target.dist_dir):
        raise SystemExit(f"❌ 构建产物目录不存在：{target.dist_dir}")


def _sync(target: FrontendTarget) -> None:
    print(f"\n--- {target.name}: 同步到 {os.path.relpath(target.asset_dir, REPO_ROOT)} ---")
    if os.path.exists(target.asset_dir):
        shutil.rmtree(target.asset_dir)
    shutil.copytree(target.dist_dir, target.asset_dir)
    size_mb = sum(
        os.path.getsize(os.path.join(directory, filename))
        for directory, _, filenames in os.walk(target.asset_dir)
        for filename in filenames
    ) / (1024 * 1024)
    print(f"✅ {target.name} 同步完成（{size_mb:.1f} MB）")


def _prepare_subset_fonts() -> None:
    """构建前生成 LXGW 子集字体并放入各端 public/fonts/（性能优化 #20）。

    源 @fontsource woff2 含 3 万+ 字形（单权重约 7MB），子集化后约 0.84MB。
    字体内容变化（文案/预设新增字符）时重跑即可更新。需要 fontTools + brotli。
    子集失败不阻断构建（回退为使用已存在的子集文件）。
    """
    import shutil
    import subprocess

    subset_script = os.path.join(REPO_ROOT, "scripts", "subset_fonts.py")
    out_dir = os.path.join(REPO_ROOT, "assets", "fonts")
    try:
        print("\n--- 字体子集化（LXGW 文楷）---")
        subprocess.run(
            [sys.executable, subset_script, "--out-dir", out_dir],
            check=True, cwd=REPO_ROOT,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"⚠️  字体子集化失败（{exc}），使用已存在的子集文件继续")

    # 将子集字体分发到各端 public/fonts/（vite 会原样拷贝到 dist/fonts/）
    for name in ("500", "700"):
        src = os.path.join(out_dir, f"lxgw-wenkai-subset-{name}.woff2")
        if not os.path.isfile(src):
            continue
        for frontend_dir in ("frontend", "frontend-v2"):
            dst_dir = os.path.join(REPO_ROOT, frontend_dir, "public", "fonts")
            os.makedirs(dst_dir, exist_ok=True)
            shutil.copy2(src, os.path.join(dst_dir, os.path.basename(src)))


def main() -> None:
    parser = argparse.ArgumentParser(description="构建旧版、V2 与 V3 Web 前端")
    parser.add_argument("--install", action="store_true", help="构建前安装依赖")
    parser.add_argument("--no-sync", action="store_true", help="仅构建，不同步到 assets")
    parser.add_argument(
        "--target",
        choices=("all", "legacy", "v2", "v3"),
        default="all",
        help="要构建的前端，默认 all",
    )
    args = parser.parse_args()

    # 旧版与 V2 使用 LXGW 子集字体（V3 用系统字体，无需子集化）
    if args.target in ("all", "legacy", "v2"):
        _prepare_subset_fonts()

    selected = list(TARGETS.values()) if args.target == "all" else [TARGETS[args.target]]
    for target in selected:
        _validate_target(target)
        if args.install:
            _install(target)
        _build(target)
        if not args.no_sync:
            _sync(target)

    print("\n✅ 所选前端全部构建完成")


if __name__ == "__main__":
    main()
