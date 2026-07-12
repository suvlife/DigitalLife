#!/usr/bin/env python3
"""Fail when checked-in product version declarations disagree with VERSION."""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
expected = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
checks: list[tuple[str, str]] = []

version_py = (ROOT / "src/version.py").read_text(encoding="utf-8")
match = re.search(r'__version__\s*=\s*["\']([^"\']+)', version_py)
checks.append(("src/version.py", match.group(1) if match else "<missing>"))

for relative in ("frontend/package.json", "frontend/package-lock.json", "frontend-v2/package.json", "frontend-v2/package-lock.json"):
    package_path = ROOT / relative
    if package_path.exists():
        package = json.loads(package_path.read_text(encoding="utf-8"))
        checks.append((relative, str(package.get("version", "<missing>"))))
        packages = package.get("packages")
        if isinstance(packages, dict) and isinstance(packages.get(""), dict):
            checks.append((relative + ' root package', str(packages[""].get("version", "<missing>"))))


dockerfile_path = ROOT / "Dockerfile"
if dockerfile_path.exists():
    dockerfile_text = dockerfile_path.read_text(encoding="utf-8")
    docker_arg_match = re.search(r"ARG APP_VERSION=([^\s]+)", dockerfile_text)
    if docker_arg_match:
        checks.append(("Dockerfile", docker_arg_match.group(1)))

compose_path = ROOT / "docker-compose.yml"
if compose_path.exists():
    compose_text = compose_path.read_text(encoding="utf-8")
    image_match = re.search(r"image:\s*digitallife:([^\s]+)", compose_text)
    if image_match:
        checks.append(("docker-compose.yml image", image_match.group(1)))
    compose_arg_match = re.search(r"APP_VERSION:\s*[\"]?([^\s\"]+)", compose_text)
    if compose_arg_match:
        checks.append(("docker-compose.yml APP_VERSION", compose_arg_match.group(1)))
readme_path = ROOT / "README.md"
if readme_path.exists():
    readme_text = readme_path.read_text(encoding="utf-8")
    badge_match = re.search(r"version-([0-9]+\.[0-9]+\.[0-9]+)-blue", readme_text)
    if badge_match:
        checks.append(("README.md badge", badge_match.group(1)))

errors = [(path, actual) for path, actual in checks if actual != expected]
if errors:
    for path, actual in errors:
        print(f"version mismatch: {path}: {actual!r} != {expected!r}", file=sys.stderr)
    raise SystemExit(1)
print(f"Version declarations are consistent: {expected}")
