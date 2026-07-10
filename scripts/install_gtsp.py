#!/usr/bin/env python3
"""Install a pinned GTSP release asset with mandatory SHA-256 verification.

No unauthenticated "latest" URL or embedded checksum is assumed. Operators
must provide a trusted release base URL and either a checksums JSON file or an
explicit expected SHA-256. This keeps the installer useful without inventing a
vendor/release location and prevents silent supply-chain downloads.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import tempfile
from urllib.parse import urlparse
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = REPO_ROOT / "assets" / "execute" / "gtsp"


def platform_id(system: str | None = None, machine: str | None = None) -> str:
    system_name = (system or platform.system()).lower()
    machine_name = (machine or platform.machine()).lower()
    systems = {"darwin": "darwin", "linux": "linux", "windows": "windows"}
    architectures = {"x86_64": "amd64", "amd64": "amd64", "arm64": "arm64", "aarch64": "arm64"}
    if system_name not in systems or machine_name not in architectures:
        raise SystemExit(f"Unsupported platform: {system_name}/{machine_name}")
    return f"{systems[system_name]}-{architectures[machine_name]}"


def asset_name(target: str) -> str:
    suffix = ".exe" if target.startswith("windows-") else ""
    return f"gtsp-{target}{suffix}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_expected_checksum(asset: str, checksum: str | None, checksum_file: str | None) -> str:
    if checksum:
        expected = checksum.strip().lower()
    elif checksum_file:
        data = json.loads(Path(checksum_file).read_text(encoding="utf-8"))
        expected = str(data.get(asset, "")).strip().lower()
    else:
        raise SystemExit("A trusted --sha256 or --checksums JSON file is required")
    if not expected or len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
        raise SystemExit(f"Missing or invalid SHA-256 for {asset}")
    return expected


def build_download_url(base_url: str, version: str, asset: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise SystemExit("--base-url must be an absolute HTTPS URL")
    return f"{base_url.rstrip('/')}/{version.strip('/')}/{asset}"


def install(url: str, destination: Path, expected_sha256: str, *, timeout: int = 60) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = Request(url, headers={"User-Agent": "DigitalLife-GTSP-Installer/1"})
    with tempfile.NamedTemporaryFile(prefix="gtsp-", delete=False, dir=destination.parent) as temp:
        temp_path = Path(temp.name)
        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310 - URL is HTTPS validated above
                shutil.copyfileobj(response, temp)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
    actual = sha256_file(temp_path)
    if actual != expected_sha256:
        temp_path.unlink(missing_ok=True)
        raise SystemExit(f"Checksum mismatch for {destination.name}: expected {expected_sha256}, got {actual}")
    if os.name != "nt":
        temp_path.chmod(0o755)
    os.replace(temp_path, destination)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="Pinned release version/path component")
    parser.add_argument("--base-url", required=True, help="Trusted HTTPS release asset base")
    parser.add_argument("--sha256", help="Expected checksum for the selected platform asset")
    parser.add_argument("--checksums", help="JSON map of asset filename to SHA-256")
    parser.add_argument("--destination-dir", type=Path, default=ASSET_DIR)
    parser.add_argument("--print-platform", action="store_true")
    args = parser.parse_args()

    target = platform_id()
    name = asset_name(target)
    if args.print_platform:
        print(target)
    checksum = load_expected_checksum(name, args.sha256, args.checksums)
    url = build_download_url(args.base_url, args.version, name)
    destination = args.destination_dir / name
    install(url, destination, checksum)
    print(f"Installed {name} -> {destination}")
    print(f"SHA-256: {checksum}")


if __name__ == "__main__":
    main()
