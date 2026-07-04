"""Skill 导入/管理服务。

支持上传 zip 包或目录形式的 Skill，解压/复制到用户 skills 目录，并重新扫描。
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
import zipfile
from typing import Any

import appPaths
import service.skillService as skillService

logger = logging.getLogger(__name__)


class SkillImportError(Exception):
    pass


def _sanitize_skill_name(name: str) -> str:
    """清理 skill 名称，仅保留字母、数字、下划线和连字符。"""
    sanitized = "".join(c for c in name if c.isalnum() or c in ("_", "-")).strip()
    if not sanitized:
        raise SkillImportError("skill 名称不合法")
    return sanitized


def _safe_extract_zip(zf: zipfile.ZipFile, extract_dir: str) -> None:
    """安全解压 zip：逐条校验 member 路径，拒绝 Zip-Slip 路径穿越与 zip 炸弹。

    每个成员的 realpath 必须落在 extract_dir 之内，否则抛出 SkillImportError。
    同时拒绝绝对路径、盘符（Windows）以及驱动器根目录条目。
    防护 zip 炸弹：限制总解压大小、条目数、单文件大小、压缩比。
    """
    _MAX_TOTAL_SIZE = 50 * 1024 * 1024  # 50MB
    _MAX_ENTRIES = 500
    _MAX_SINGLE_FILE = 20 * 1024 * 1024  # 20MB
    _MAX_COMPRESSION_RATIO = 100  # 100:1

    members = zf.infolist()
    if len(members) > _MAX_ENTRIES:
        raise SkillImportError(f"zip 条目数过多({len(members)})，上限 {_MAX_ENTRIES}")

    total_uncompressed = 0
    extract_dir_real = os.path.realpath(extract_dir)
    for member in members:
        member_name = member.filename
        # 拒绝绝对路径与 Windows 盘符
        if os.path.isabs(member_name) or member_name.startswith(("/", "\\")):
            raise SkillImportError(f"zip 包含不安全的绝对路径条目: {member_name}")
        if len(member_name) >= 2 and member_name[1] == ":":
            raise SkillImportError(f"zip 包含不安全的盘符条目: {member_name}")
        target_path = os.path.realpath(os.path.join(extract_dir_real, member_name))
        if target_path != extract_dir_real and not target_path.startswith(
            extract_dir_real + os.sep
        ):
            raise SkillImportError(f"zip 包含路径穿越条目: {member_name}")

        # zip 炸弹防护
        file_size = member.file_size
        compress_size = member.compress_size
        if file_size > _MAX_SINGLE_FILE:
            raise SkillImportError(
                f"zip 单文件过大: {member_name} ({file_size} bytes)，上限 {_MAX_SINGLE_FILE} bytes"
            )
        total_uncompressed += file_size
        if total_uncompressed > _MAX_TOTAL_SIZE:
            raise SkillImportError(
                f"zip 总解压大小超过上限: {total_uncompressed} bytes，上限 {_MAX_TOTAL_SIZE} bytes"
            )
        if compress_size > 0 and file_size / compress_size > _MAX_COMPRESSION_RATIO:
            raise SkillImportError(
                f"zip 压缩比异常({file_size / compress_size:.0f}:1): {member_name}"
            )

    zf.extractall(extract_dir)


def _validate_skill_directory(skill_dir: str) -> dict[str, Any]:
    """校验目录是否符合 skill 规范，返回解析后的元信息。"""
    skill_md = os.path.join(skill_dir, "SKILL.md")
    if not os.path.isfile(skill_md):
        raise SkillImportError(f"目录缺少 SKILL.md: {skill_dir}")

    info = skillService.load_skill_from_disk(skill_dir, is_builtin=False)
    if info is None:
        raise SkillImportError(f"无法解析 SKILL.md，请检查 front-matter")
    return {
        "name": info.name,
        "description": info.description,
        "files": info.files,
    }


def _move_to_user_skills(src_dir: str, skill_name: str) -> str:
    """将临时目录中的 skill 移动到用户 skills 目录。"""
    target_dir = os.path.join(appPaths.USER_SKILLS_DIR, skill_name)
    if os.path.exists(target_dir):
        shutil.rmtree(target_dir)
    shutil.move(src_dir, target_dir)
    return target_dir


async def import_skill_from_zip(zip_bytes: bytes, force: bool = False) -> dict[str, Any]:
    """从 zip 包导入 skill。

    Args:
        zip_bytes: zip 文件二进制内容
        force: 是否覆盖已存在的 skill

    Returns:
        {"success": True, "name": ..., "description": ..., "dir": ...}
    """
    # 解压、移动等均为同步阻塞 IO，丢到线程池执行以避免冻结事件循环。
    return await asyncio.to_thread(_do_import_skill_from_zip, zip_bytes, force)


def _do_import_skill_from_zip(zip_bytes: bytes, force: bool = False) -> dict[str, Any]:
    """import_skill_from_zip 的同步实现（线程池中执行）。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = os.path.join(tmpdir, "skill.zip")
        with open(zip_path, "wb") as f:
            f.write(zip_bytes)

        extract_dir = os.path.join(tmpdir, "extracted")
        os.makedirs(extract_dir, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as z:
            _safe_extract_zip(z, extract_dir)

        # 支持两种打包格式：
        # 1) zip 根目录直接是 skill 文件（SKILL.md 在根）
        # 2) zip 根目录是一个子文件夹，里面是 skill 文件
        candidate_dirs = []
        if os.path.isfile(os.path.join(extract_dir, "SKILL.md")):
            candidate_dirs.append(extract_dir)
        for entry in os.listdir(extract_dir):
            entry_path = os.path.join(extract_dir, entry)
            if os.path.isdir(entry_path) and os.path.isfile(os.path.join(entry_path, "SKILL.md")):
                candidate_dirs.append(entry_path)

        if not candidate_dirs:
            raise SkillImportError("zip 包中未找到 SKILL.md")

        # 一次只导入一个 skill；如果找到多个，取第一个并提示
        skill_dir = candidate_dirs[0]
        meta = _validate_skill_directory(skill_dir)
        skill_name = _sanitize_skill_name(meta["name"])

        target_dir = os.path.join(appPaths.USER_SKILLS_DIR, skill_name)
        if os.path.exists(target_dir) and not force:
            raise SkillImportError(f"skill '{skill_name}' 已存在，设置 force=true 可覆盖")

        final_dir = _move_to_user_skills(skill_dir, skill_name)
        skillService.startup()  # 重新扫描索引

        return {
            "success": True,
            "name": skill_name,
            "description": meta["description"],
            "dir": final_dir,
        }


async def import_skill_from_directory(src_dir: str, force: bool = False) -> dict[str, Any]:
    """从本地目录导入 skill（服务器端使用）。"""
    if not os.path.isdir(src_dir):
        raise SkillImportError(f"目录不存在: {src_dir}")

    meta = _validate_skill_directory(src_dir)
    skill_name = _sanitize_skill_name(meta["name"])

    target_dir = os.path.join(appPaths.USER_SKILLS_DIR, skill_name)
    if os.path.exists(target_dir) and not force:
        raise SkillImportError(f"skill '{skill_name}' 已存在，设置 force=true 可覆盖")

    if os.path.exists(target_dir):
        shutil.rmtree(target_dir)
    shutil.copytree(src_dir, target_dir)
    skillService.startup()

    return {
        "success": True,
        "name": skill_name,
        "description": meta["description"],
        "dir": target_dir,
    }


async def delete_user_skill(skill_name: str) -> dict[str, Any]:
    """删除用户导入的 skill（builtin skill 不允许删除）。"""
    skill_name = _sanitize_skill_name(skill_name)
    target_dir = os.path.join(appPaths.USER_SKILLS_DIR, skill_name)
    if not os.path.exists(target_dir):
        raise SkillImportError(f"skill '{skill_name}' 不存在")

    info = skillService.get_skill(skill_name)
    if info is not None and info.is_builtin:
        raise SkillImportError(f"builtin skill '{skill_name}' 不允许删除")

    shutil.rmtree(target_dir)
    skillService.startup()
    return {"success": True, "name": skill_name}
