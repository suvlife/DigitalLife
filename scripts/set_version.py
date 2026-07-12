#!/usr/bin/env python3
"""Set repository version declarations from one command."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("version", help="Semantic version without a leading v")
args = parser.parse_args()
version = args.version.strip().removeprefix("v")
if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", version):
    raise SystemExit("invalid semantic version")
(ROOT / "VERSION").write_text(version + "\n", encoding="utf-8")
(ROOT / "src/version.py").write_text(f'__version__ = "{version}"\n', encoding="utf-8")
for relative in ("frontend/package.json", "frontend/package-lock.json", "frontend-v2/package.json", "frontend-v2/package-lock.json"):
    path = ROOT / relative
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        data["version"] = version
        if isinstance(data.get("packages"), dict) and isinstance(data["packages"].get(""), dict):
            data["packages"][""]["version"] = version
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

for relative, pattern, replacement in (
    ("docker-compose.yml", r"(image:\s*digitallife:)[^\s]+", rf"\g<1>{version}"),
    ("docker-compose.yml", r"(APP_VERSION:\s*[\"]?)[0-9A-Za-z.+-]+", rf"\g<1>{version}"),
    ("Dockerfile", r"ARG APP_VERSION=[^\s]+", f"ARG APP_VERSION={version}"),
):
    path = ROOT / relative
    if path.exists():
        text = path.read_text(encoding="utf-8")
        path.write_text(re.sub(pattern, replacement, text), encoding="utf-8")

print(version)
