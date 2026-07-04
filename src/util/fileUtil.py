import os

from exception import TogoException


def ensure_dir(path: str) -> None:
    """确保目录存在。若不存在则创建，创建失败时抛出 TogoException。"""
    if os.path.exists(path):
        return
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as e:
        raise TogoException(
            f"无法创建目录 '{path}': {e.strerror}",
            error_code="directory_create_failed",
        )


def validate_absolute_path(path: str) -> None:
    """验证路径是否为绝对路径（Unix 的 / 或 Windows 的盘符）或以 ~ 开头。
    若校验不通过则抛出 TogoException。
    """
    if not (os.path.isabs(path) or path.startswith("~")):
        raise TogoException(
            f"路径必须为绝对路径或以 ~ 开头，不支持相对路径：{path}",
            error_code="invalid_path_format",
        )


def assert_path_within_sandbox(path: str, sandbox_root: str) -> None:
    """校验 path 解析后必须落在 sandbox_root 之内，防止路径穿越逃逸沙箱。

    用于 working_directory 等用户可配置的路径，防止指向 /etc、~/.ssh 等敏感目录。
    """
    if not path:
        raise TogoException("路径不能为空", error_code="invalid_path")
    sandbox_real = os.path.realpath(sandbox_root)
    # 展开 ~ 并解析为绝对路径
    expanded = os.path.expanduser(path)
    if not os.path.isabs(expanded):
        raise TogoException(
            f"路径必须为绝对路径：{path}",
            error_code="invalid_path_format",
        )
    target_real = os.path.realpath(expanded)
    if target_real != sandbox_real and not target_real.startswith(sandbox_real + os.sep):
        raise TogoException(
            f"路径 '{path}' 必须在工作空间根目录 '{sandbox_root}' 之内",
            error_code="path_outside_sandbox",
        )
