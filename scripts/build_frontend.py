#!/usr/bin/env python3
"""构建并同步 DigitalLife 的旧版与 V2 Web 前端。"""

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


def main() -> None:
    parser = argparse.ArgumentParser(description="构建旧版与 V2 Web 前端")
    parser.add_argument("--install", action="store_true", help="构建前安装依赖")
    parser.add_argument("--no-sync", action="store_true", help="仅构建，不同步到 assets")
    parser.add_argument(
        "--target",
        choices=("all", "legacy", "v2"),
        default="all",
        help="要构建的前端，默认 all",
    )
    args = parser.parse_args()

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
