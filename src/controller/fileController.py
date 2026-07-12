"""文件上传/下载/预览控制器。"""
from __future__ import annotations

import asyncio
import mimetypes
import os
import re
from pathlib import PureWindowsPath
from urllib.parse import quote, unquote

from tornado.iostream import StreamClosedError

from controller.baseController import BaseHandler
from exception import TogoException
from util import configUtil, fileUtil

_PREVIEW_TEXT_EXTENSIONS = {"txt", "md", "markdown", "json", "csv", "py", "js", "ts", "sql", "yaml", "yml"}
_PREVIEW_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "svg"}
_MAX_PREVIEW_TEXT_LENGTH = 10000
_DOWNLOAD_CHUNK_SIZE = max(64 * 1024, int(os.environ.get("DIGITALLIFE_DOWNLOAD_CHUNK_SIZE", 256 * 1024)))
_MAX_DOWNLOAD_BYTES = max(1, int(os.environ.get("DIGITALLIFE_MAX_DOWNLOAD_BYTES", 512 * 1024 * 1024)))
_MAX_CONCURRENT_DOWNLOADS = max(1, int(os.environ.get("DIGITALLIFE_MAX_CONCURRENT_DOWNLOADS", 4)))
_DOWNLOAD_ACQUIRE_TIMEOUT = max(0.1, float(os.environ.get("DIGITALLIFE_DOWNLOAD_ACQUIRE_TIMEOUT", "2")))
_DOWNLOAD_SEMAPHORE = asyncio.Semaphore(_MAX_CONCURRENT_DOWNLOADS)
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def _content_disposition(filename: str) -> str:
    """Build a header-safe attachment filename with RFC 5987 UTF-8 support."""
    cleaned = _CONTROL_CHARS.sub("_", filename).replace("/", "_").replace("\\", "_")
    cleaned = cleaned.strip() or "download"
    ascii_name = cleaned.encode("ascii", "ignore").decode("ascii")
    ascii_name = ascii_name.replace('"', "_").replace(";", "_").strip() or "download"
    encoded = quote(cleaned, safe="!#$&+-.^_`|~")
    return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{encoded}'


def _resolve_workspace_root() -> str:
    """获取工作空间根目录。"""
    root = configUtil.get_app_config().setting.workspace_root
    if not root:
        raise TogoException("workspace_root 未配置", error_code="workspace_not_configured")
    return os.path.realpath(os.path.expanduser(root))


async def _resolve_team_file_path(team_id: int, relative_path: str) -> str:
    """将团队工作目录中的相对路径解析为绝对路径。"""
    if not relative_path:
        raise TogoException("文件路径不能为空", error_code="invalid_path")
    if "\x00" in relative_path:
        raise TogoException("文件路径不合法", error_code="invalid_path")
    if os.path.isabs(relative_path) or PureWindowsPath(relative_path).is_absolute():
        raise TogoException("只允许团队工作目录相对路径", error_code="absolute_path_forbidden")

    from dal.db import gtTeamManager
    team = await gtTeamManager.get_team_by_id(team_id)
    if team is None or getattr(team, "deleted", 0):
        raise TogoException("团队不存在", error_code="team_not_found")

    workspace_root = _resolve_workspace_root()
    configured = (team.config or {}).get("working_directory")
    team_workdir = os.path.realpath(os.path.expanduser(configured or os.path.join(workspace_root, team.name)))
    fileUtil.assert_path_within_sandbox(team_workdir, workspace_root)

    candidate = os.path.realpath(os.path.join(team_workdir, relative_path))
    fileUtil.assert_path_within_sandbox(candidate, team_workdir)
    return candidate


def _file_error(handler: BaseHandler, error: TogoException) -> None:
    status = 404 if error.error_code == "team_not_found" else 400
    handler.set_status(status)
    handler.return_json({"error_code": error.error_code, "error_desc": error.error_message})


class FileDownloadHandler(BaseHandler):
    """GET /files/download.json?team_id=<id>&path=<relative_path>。"""

    async def get(self) -> None:
        team_id_raw = self.get_argument("team_id", "")
        if not team_id_raw:
            self.set_status(400)
            self.return_json({"error_code": "team_id_required", "error_desc": "必须指定 team_id"})
            return
        try:
            team_id = int(team_id_raw)
        except ValueError:
            self.set_status(400)
            self.return_json({"error_code": "invalid_team_id", "error_desc": "team_id 必须为整数"})
            return
        await self._assert_team_owned(team_id)
        raw_path = self.get_argument("path", "")
        path = unquote(raw_path) if raw_path else ""
        try:
            real_path = await _resolve_team_file_path(team_id, path)
        except TogoException as e:
            _file_error(self, e)
            return

        if not os.path.isfile(real_path):
            self.set_status(404)
            self.return_json({"error_code": "file_not_found", "error_desc": "文件不存在"})
            return

        try:
            file_size = await asyncio.to_thread(os.path.getsize, real_path)
        except OSError as e:
            self.set_status(500)
            self.return_json({"error_code": "read_error", "error_desc": str(e)})
            return
        if file_size > _MAX_DOWNLOAD_BYTES:
            self.set_status(413)
            self.return_json({
                "error_code": "file_too_large",
                "error_desc": f"文件超过下载上限（{_MAX_DOWNLOAD_BYTES} 字节）",
            })
            return

        try:
            await asyncio.wait_for(_DOWNLOAD_SEMAPHORE.acquire(), timeout=_DOWNLOAD_ACQUIRE_TIMEOUT)
        except TimeoutError:
            self.set_status(503)
            self.set_header("Retry-After", "2")
            self.return_json({"error_code": "download_busy", "error_desc": "下载请求过多，请稍后重试"})
            return

        streamed = False
        try:
            file_obj = await asyncio.to_thread(open, real_path, "rb")
            filename = os.path.basename(real_path)
            mime_type, _ = mimetypes.guess_type(real_path)
            self.set_header("Content-Type", mime_type or "application/octet-stream")
            self.set_header("Content-Length", str(file_size))
            self.set_header("Content-Disposition", _content_disposition(filename))
            try:
                while True:
                    chunk = await asyncio.to_thread(file_obj.read, _DOWNLOAD_CHUNK_SIZE)
                    if not chunk:
                        break
                    self.write(chunk)
                    await self.flush()
                    streamed = True
            finally:
                await asyncio.to_thread(file_obj.close)
        except StreamClosedError:
            # The client cancelled the download; stop reading without retaining resources.
            return
        except OSError as e:
            if not streamed:
                self.set_status(500)
                self.return_json({"error_code": "read_error", "error_desc": str(e)})
        finally:
            _DOWNLOAD_SEMAPHORE.release()


class FilePreviewHandler(BaseHandler):
    """GET /files/preview.json?team_id=<id>&path=<relative_path>。"""

    async def get(self) -> None:
        team_id_raw = self.get_argument("team_id", "")
        if not team_id_raw:
            self.set_status(400)
            self.return_json({"error_code": "team_id_required", "error_desc": "必须指定 team_id"})
            return
        try:
            team_id = int(team_id_raw)
        except ValueError:
            self.set_status(400)
            self.return_json({"error_code": "invalid_team_id", "error_desc": "team_id 必须为整数"})
            return
        await self._assert_team_owned(team_id)
        raw_path = self.get_argument("path", "")
        path = unquote(raw_path) if raw_path else ""
        try:
            real_path = await _resolve_team_file_path(team_id, path)
        except TogoException as e:
            _file_error(self, e)
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
            result["url"] = f"/files/download.json?team_id={team_id}&path={quote(path)}"
        elif ext == "pdf":
            result["preview_type"] = "pdf"
            result["url"] = f"/files/download.json?team_id={team_id}&path={quote(path)}"

        self.return_json(result)
