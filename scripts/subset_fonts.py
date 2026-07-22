#!/usr/bin/env python3
"""LXGW 文楷字体子集化（前端性能 #20）。

`@fontsource/lxgw-wenkai` 的 "latin" 命名有误导性：其 woff2 实际含 3 万+ 字形
（其中 2 万+ 是 CJK 统一表意文字），单权重约 7MB，两个权重共 ~14MB，且
`index.css` 无 unicode-range 子集。默认入口 V2 与经典 V1 的首屏都被这 14MB 拖累。

本脚本按"项目实际用到的字符集 ∪ GB2312 一级常用字"对源字体做子集化：
- 收集三端源码与预设 JSON 中出现的全部字符（覆盖 UI 文案与团队/角色预设名）；
- 并入 GB2312 一级常用字（3755 字），兜底用户动态输入与团队自定义命名；
- 叠加 ASCII 可打印字符、常用标点与全角符号。

产物为子集后的 woff2（体积从 ~7MB 降至约 1MB 量级），配合前端 fonts.css
改为引用本地子集文件即可生效。子集是一次性构建步骤，源字体文案变化时重跑。

用法：
    .venv/bin/python scripts/subset_fonts.py
    .venv/bin/python scripts/subset_fonts.py --dry-run   # 只统计不写出
"""
from __future__ import annotations

import argparse
import glob
import os
import sys

from fontTools import subset

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# 需要子集化的字体（fontsource 包内 woff2），键为目标权重目录名
FONT_SOURCES = {
    "500": "frontend-v2/node_modules/@fontsource/lxgw-wenkai/files/lxgw-wenkai-latin-500-normal.woff2",
    "700": "frontend-v2/node_modules/@fontsource/lxgw-wenkai/files/lxgw-wenkai-latin-700-normal.woff2",
}

# 收集字符集的源码与预设路径
TEXT_GLOBS = [
    "frontend/src/**/*.vue", "frontend/src/**/*.ts",
    "frontend-v2/src/**/*.vue", "frontend-v2/src/**/*.ts",
    "frontend-v3/src/**/*.vue", "frontend-v3/src/**/*.ts",
    "assets/preset/**/*.json",
    "frontend/index.html", "frontend-v2/index.html", "frontend-v3/index.html",
]


def _gb2312_level1_chars() -> set[str]:
    """GB2312 一级常用汉字（3755 字），兜底动态内容与自定义命名。

    GB2312 一级字区位于编码 0xB0A1–0xD7F9。逐字节对解码得到字符集。
    """
    chars: set[str] = set()
    for hi in range(0xB0, 0xD8):
        for lo in range(0xA1, 0xFF):
            if hi == 0xD7 and lo > 0xF9:
                break
            try:
                chars.add(bytes([hi, lo]).decode("gb2312"))
            except UnicodeDecodeError:
                continue
    return chars


def collect_charset() -> set[str]:
    """汇总源码 + 预设 + GB2312 一级字 + ASCII 与常用符号的目标字符集。"""
    text = ""
    for pattern in TEXT_GLOBS:
        for path in glob.glob(os.path.join(REPO_ROOT, pattern), recursive=True):
            try:
                with open(path, encoding="utf-8") as f:
                    text += f.read()
            except (OSError, UnicodeDecodeError):
                continue
    charset = set(text)
    charset |= _gb2312_level1_chars()
    # ASCII 可打印字符 + 常用全角标点/符号
    charset |= {chr(c) for c in range(0x20, 0x7F)}
    charset |= set("，。！？；：、“”‘’（）《》〈〉【】—…·～％　")
    return charset


def subset_font(weight: str, src_rel: str, charset: set[str], out_dir: str, dry_run: bool) -> None:
    src = os.path.join(REPO_ROOT, src_rel)
    if not os.path.isfile(src):
        print(f"⚠️  跳过（源字体不存在）：{src_rel}")
        return
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"lxgw-wenkai-subset-{weight}.woff2")

    if dry_run:
        print(f"[dry-run] {weight}: 源 {os.path.getsize(src)/1024/1024:.1f}MB, 目标字符 {len(charset)}")
        return

    options = subset.Options()
    options.flavor = "woff2"
    options.desubroutinize = True
    options.name_IDs = ["*"]        # 保留命名字段（许可要求保留字体名/版权）
    options.notdef_outline = True
    options.recalc_bounds = True

    font = subset.load_font(src, options)
    subsetter = subset.Subsetter(options)
    subsetter.populate(text="".join(sorted(charset)))
    subsetter.subset(font)
    font.save(out_path)

    src_mb = os.path.getsize(src) / 1024 / 1024
    out_mb = os.path.getsize(out_path) / 1024 / 1024
    print(f"✅ {weight}: {src_mb:.1f}MB → {out_mb:.2f}MB（{out_path}）")


def main() -> None:
    parser = argparse.ArgumentParser(description="LXGW 文楷字体子集化")
    parser.add_argument("--dry-run", action="store_true", help="只统计字符集，不写出文件")
    parser.add_argument("--out-dir", default=os.path.join(REPO_ROOT, "assets", "fonts"),
                        help="子集字体输出目录（默认 assets/fonts）")
    args = parser.parse_args()

    charset = collect_charset()
    cjk = sum(1 for c in charset if "一" <= c <= "鿿")
    print(f"目标字符集：{len(charset)} 字符（含 CJK {cjk}）")
    for weight, src in FONT_SOURCES.items():
        subset_font(weight, src, charset, args.out_dir, args.dry_run)


if __name__ == "__main__":
    main()
