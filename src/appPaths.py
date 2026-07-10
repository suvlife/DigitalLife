"""
运行时路径模块。

引入 STORAGE_ROOT 统一管理所有可写目录：
- 打包模式：~/.togospace
- 开发模式：仓库根目录下的 dev_storage_root/

静态资源（只读）在打包时指向 _MEIPASS，开发时指向仓库 assets/。
"""
import os
import platform
import sys

_SRC = os.path.dirname(os.path.abspath(__file__))   # = repo/src/
_ROOT = os.path.join(_SRC, "..")                     # = repo/
_IS_FROZEN = bool(getattr(sys, "frozen", False))
_MEIPASS = str(getattr(sys, "_MEIPASS", ""))
IS_DEV_MODE = not _IS_FROZEN

STORAGE_ROOT: str
ASSETS_DIR: str
DATA_DIR: str
LOGS_DIR: str
WORKSPACE_ROOT: str
CONFIG_DIR: str
PRESET_DIR: str

if _IS_FROZEN:
    STORAGE_ROOT = os.path.expanduser("~/.togospace")
    ASSETS_DIR = os.path.join(_MEIPASS, "assets")
else:
    STORAGE_ROOT = os.path.abspath(os.path.join(_ROOT, "dev_storage_root"))
    ASSETS_DIR = os.path.abspath(os.path.join(_ROOT, "assets"))

# 环境变量优先级最高（用于 Docker 等场景）
_ENV_STORAGE_ROOT = os.environ.get("STORAGE_ROOT")
if _ENV_STORAGE_ROOT:
    STORAGE_ROOT = _ENV_STORAGE_ROOT
DATA_DIR = os.path.join(STORAGE_ROOT, "data")
LOGS_DIR = os.path.join(STORAGE_ROOT, "logs", "backend")
WORKSPACE_ROOT = os.path.join(STORAGE_ROOT, "workspace")
BUILTIN_SKILLS_DIR = os.path.join(ASSETS_DIR, "skills")
USER_SKILLS_DIR = os.path.join(STORAGE_ROOT, "skills")
CONFIG_DIR = STORAGE_ROOT
PRESET_DIR = os.path.abspath(os.environ.get("TEAMAGENT_PRESET_DIR") or os.path.join(ASSETS_DIR, "preset"))


def get_gtsp_platform_id(*, system: str | None = None, machine: str | None = None) -> str:
    """Return the release asset platform id used by GTSP binaries."""
    system_name = (system or platform.system()).lower()
    machine_name = (machine or platform.machine()).lower()
    system_map = {"darwin": "darwin", "linux": "linux", "windows": "windows"}
    arch_map = {"x86_64": "amd64", "amd64": "amd64", "arm64": "arm64", "aarch64": "arm64"}
    if system_name not in system_map or machine_name not in arch_map:
        raise RuntimeError(
            f"Unsupported GTSP platform: system={system_name}, machine={machine_name}. "
            "Set a custom TSP command or use the native driver."
        )
    return f"{system_map[system_name]}-{arch_map[machine_name]}"


def get_gtsp_binary_path(*, require_exists: bool = True) -> str:
    """Return the expected GTSP executable path for the current platform.

    ``require_exists=False`` is useful for diagnostics/installers and never
    causes application startup to fail by itself.
    """
    platform_id = get_gtsp_platform_id()
    suffix = ".exe" if platform_id.startswith("windows-") else ""
    binary_path = os.path.join(ASSETS_DIR, "execute", "gtsp", f"gtsp-{platform_id}{suffix}")
    if require_exists and not os.path.isfile(binary_path):
        raise FileNotFoundError(
            "GTSP executable is not installed. "
            f"Expected: {binary_path}. Run 'python scripts/install_gtsp.py --version <version> "
            "--base-url <trusted-release-base> --checksums <checksums.json>', configure a custom "
            "TSP command, or enable driver_fallback.tsp_to_native."
        )
    if require_exists and os.name != "nt" and not os.access(binary_path, os.X_OK):
        raise PermissionError(f"GTSP executable is not executable: {binary_path}")
    return binary_path


def gtsp_diagnostic() -> dict[str, str | bool]:
    try:
        expected = get_gtsp_binary_path(require_exists=False)
        available = os.path.isfile(expected) and (os.name == "nt" or os.access(expected, os.X_OK))
        return {"available": available, "path": expected, "platform": get_gtsp_platform_id()}
    except RuntimeError as exc:
        return {"available": False, "path": "", "platform": "unsupported", "error": str(exc)}
