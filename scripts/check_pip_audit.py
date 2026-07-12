#!/usr/bin/env python3
"""Validate pip-audit JSON so tool/network failures cannot masquerade as success."""
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    report = json.loads(path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    raise SystemExit(f"invalid pip-audit report: {exc}")
if not isinstance(report, dict) or not isinstance(report.get("dependencies"), list):
    raise SystemExit("invalid pip-audit report schema")
vulnerabilities = sum(len(dep.get("vulns", [])) for dep in report["dependencies"] if isinstance(dep, dict))
print(f"pip-audit report parsed: {len(report['dependencies'])} dependencies, {vulnerabilities} vulnerabilities")
