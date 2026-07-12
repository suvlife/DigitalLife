#!/usr/bin/env python3
"""Low-noise repository secret and sensitive-log scanner.

Only tracked source/config files are scanned. The rules intentionally target
high-confidence credential formats and logging calls that interpolate plainly
named secret variables; generic words such as "token" do not fail CI.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {
    ".py", ".js", ".ts", ".tsx", ".vue", ".json", ".yml", ".yaml", ".toml",
    ".ini", ".cfg", ".conf", ".sh", ".md", ".txt", ".env", ".example",
}
SKIP_PREFIXES = ("tests/", "assets/", "frontend/dist/", "frontend-v2/dist/")
SKIP_NAMES = {"package-lock.json", "security_scan.py"}

SECRET_RULES = (
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{60,})\b")),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("OpenAI-style key", re.compile(r"\bsk-[A-Za-z0-9_-]{32,}\b")),
)
LOG_CALL = re.compile(r"\b(?:logger|logging)\.(?:debug|info|warning|error|exception|critical)\s*\(")
SENSITIVE_NAME = re.compile(r"\b(?:password|passwd|secret|api_key|access_token|refresh_token|auth_token|private_key)\b", re.I)
SAFE_LOG_CONTEXT = re.compile(r"(?:missing|configured|enabled|disabled|invalid|redacted|masked|failed|success)", re.I)


def tracked_files() -> list[Path]:
    output = subprocess.check_output(
        ["git", "ls-files", "-co", "--exclude-standard"], cwd=ROOT, text=True
    )
    files: list[Path] = []
    for relative in output.splitlines():
        path = ROOT / relative
        if not path.is_file() or path.name in SKIP_NAMES:
            continue
        if relative.startswith(SKIP_PREFIXES):
            continue
        if path.suffix.lower() in TEXT_SUFFIXES or path.name.startswith(".env"):
            files.append(path)
    return files


def main() -> int:
    findings: list[str] = []
    for path in tracked_files():
        relative = path.relative_to(ROOT)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(lines, 1):
            for label, pattern in SECRET_RULES:
                if pattern.search(line):
                    findings.append(f"{relative}:{number}: possible {label}")
            if LOG_CALL.search(line) and SENSITIVE_NAME.search(line) and not SAFE_LOG_CONTEXT.search(line):
                findings.append(f"{relative}:{number}: possible sensitive value in log call")

    if findings:
        print("Security scan found high-confidence issues:", file=sys.stderr)
        print("\n".join(f"- {item}" for item in findings), file=sys.stderr)
        return 1
    print("Security scan passed: no high-confidence secrets or sensitive log calls found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
