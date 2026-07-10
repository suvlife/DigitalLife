import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "install_gtsp.py"
spec = importlib.util.spec_from_file_location("install_gtsp", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def test_platform_and_asset_names() -> None:
    assert module.platform_id("Darwin", "arm64") == "darwin-arm64"
    assert module.asset_name("windows-amd64") == "gtsp-windows-amd64.exe"


def test_checksum_file(tmp_path) -> None:
    path = tmp_path / "asset"
    path.write_bytes(b"abc")
    assert module.sha256_file(path) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
