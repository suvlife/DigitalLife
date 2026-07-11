"""文件上传/下载/预览控制器。"""
from __future__ import annotations

import logging
import mimetypes
import os
from urllib.parse import unquote

import tornado.web
from controller.baseController import BaseHandler
from exception import TogoException
from service import roomService
from util import configUtil, fileUtil

logger = logging.getLogger(__name__)

_MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
_ALLOWED_EXTENSIONS = {
    "txt", "md", "markdown", "json", "csv", "pdf", "doc", "docx", "ppt", "pptx", "xlsx", "xls",
    "png", "jpg", "jpeg", "gif", "svg", "zip",
    "py", "js", "ts", "sql", "yaml", "yml",
}
_PREVIEW_TEXT_EXTENSIONS = {"txt", "md", "markdown", "json", "csv", "py", "js", "ts", "sql", "yaml", "yml"}
_PREVIEW_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "svg"}
_MAX_PREVIEW_TEXT_LENGTH = 10000


def _resolve_workspace_root() -> str:
    """获取工作空间根目录。"""
    root = configUtil.get_app_config().setting.workspace_root
    if not root:
        raise TogoException("workspace_root 未配置", error_code="workspace_not_configured")
    return os.path.abspath(root)


def _validate_file_path(path: str) -> str:
    """校验文件路径在工作空间内，返回绝对路径。"""
    if not path:
        raise TogoException("文件路径不能为空", error_code="invalid_path")
    workspace_root = _resolve_workspace_root()
    fileUtil.assert_path_within_sandbox(path, workspace_root)
    return os.path.realpath(path)


class FileDownloadHandler(BaseHandler):
    """GET /files/download.json?path=<encoded_path> — 下载工作目录内的文件。"""

    async def get(self) -> None:
        raw_path = self.get_argument("path", "")
        path = unquote(raw_path) if raw_path else ""
        try:
            real_path = _validate_file_path(path)
        except TogoException as e:
            self.set_status(400)
            self.return_json({"error_code": e.error_code, "error_desc": e.error_message})
            return

        if not os.path.isfile(real_path):
            self.set_status(404)
            self.return_json({"error_code": "file_not_found", "error_desc": "文件不存在"})
            return

        filename = os.path.basename(real_path)
        mime_type, _ = mimetypes.guess_type(real_path)
        if mime_type is None:
            mime_type = "application/octet-stream"

        self.set_header("Content-Type", mime_type)
        self.set_header("Content-Disposition", f'attachment; filename="{filename}"')
        try:
            with open(real_path, "rb") as f:
                self.write(f.read())
        except OSError as e:
            self.set_status(500)
            self.return_json({"error_code": "read_error", "error_desc": str(e)})


class FilePreviewHandler(BaseHandler):
    """GET /files/preview.json?path=<encoded_path> — 返回文件预览信息。"""

    async def get(self) -> None:
        raw_path = self.get_argument("path", "")
        path = unquote(raw_path) if raw_path else ""
        try:
            real_path = _validate_file_path(path)
        except TogoException as e:
            self.set_status(400)
            self.return_json({"error_code": e.error_code, "error_desc": e.error_message})
            return

        if not os.path.isfile(real_path):
            self.set_status(404)
            self.return_json({"error_code": "file_not_found", "error_desc": "文件不存在"})
            return

        filename = os.path.basename(real_path)
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        file_size = os.path.getsize(real_path)

        result: dict = {
            "filename": filename,
            "size": file_size,
            "extension": ext,
            "preview_type": "download",  # 默认只能下载
        }

        if ext in _PREVIEW_TEXT_EXTENSIONS:
            try:
                with open(real_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read(_MAX_PREVIEW_TEXT_LENGTH + 1)
                truncated = len(content) > _MAX_PREVIEW_TEXT_LENGTH
                if truncated:
                    content = content[:_MAX_PREVIEW_TEXT_LENGTH]
                result["preview_type"] = "text"
                result["content"] = content
                result["truncated"] = truncated
            except OSError:
                pass
        elif ext in _PREVIEW_IMAGE_EXTENSIONS:
            result["preview_type"] = "image"
            result["url"] = f"/files/download.json?path={raw_path}"
        elif ext == "pdf":
            result["preview_type"] = "pdf"
            result["url"] = f"/files/download.json?path={raw_path}"

        self.return_json(result)
