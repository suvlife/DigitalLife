"""Skill 服务：扫描、索引、查询、加载 Skill 资源。"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

import yaml
import appPaths

logger = logging.getLogger(__name__)

_SKILL_MD = "SKILL.md"
_SKILL_BINDINGS_FILE = "skill_bindings.json"

# 全体成员常驻的产品级技能（文档/表格/PPT 生产）。可被 skill_bindings.json 覆盖。
_DEFAULT_PRODUCT_SKILLS: list[str] = [
    "document-studio", "spreadsheet-studio", "guizang-ppt-skill",
]


@dataclass
class SkillInfo:
    """Skill 的索引信息，启动时扫描生成。"""
    name: str
    description: str
    skill_dir: str
    is_builtin: bool = True
    content: str = ""
    files: list[str] = field(default_factory=list)


_registry: dict[str, SkillInfo] = {}

# 工作类型 → 技能绑定表，由 skill_bindings.json 加载。
_product_skills: list[str] = list(_DEFAULT_PRODUCT_SKILLS)
_role_skills: dict[str, list[str]] = {}


def _scan_skills_in_dir(scan_dir: str, is_builtin: bool) -> None:
    if not os.path.isdir(scan_dir):
        logger.info("Skill 目录不存在，跳过扫描: %s", scan_dir)
        return

    for entry in os.listdir(scan_dir):
        skill_dir = os.path.join(scan_dir, entry)
        if not os.path.isdir(skill_dir):
            continue

        skill_info = load_skill_from_disk(skill_dir, is_builtin=is_builtin)
        if skill_info:
            if skill_info.name in _registry:
                logger.info("覆盖同名 Skill: %s (原 is_builtin=%s, 新 is_builtin=%s)", 
                            skill_info.name, _registry[skill_info.name].is_builtin, is_builtin)
            _registry[skill_info.name] = skill_info
            logger.info("已加载 Skill: %s (%s) [builtin=%s]", skill_info.name, skill_info.description[:50], is_builtin)

def startup() -> None:
    """扫描 assets/skills/ 目录以及 storage_root 的 skills 目录，构建全局 Skill 索引。"""
    global _registry
    _registry = {}

    try:
        os.makedirs(appPaths.USER_SKILLS_DIR, exist_ok=True)
        if "PYTEST_CURRENT_TEST" not in os.environ:
            from util.configUtil import sync_file_if_changed
            sync_file_if_changed("docs/skills.README.md", appPaths.USER_SKILLS_DIR, "README.md")
    except OSError as e:
        logger.warning("无法创建 USER_SKILLS_DIR: %s", e)

    _scan_skills_in_dir(appPaths.BUILTIN_SKILLS_DIR, is_builtin=True)
    _scan_skills_in_dir(appPaths.USER_SKILLS_DIR, is_builtin=False)

    _load_skill_bindings()

    logger.info("Skill 索引构建完成，共 %d 个 Skill", len(_registry))


def load_skill_from_disk(skill_dir: str, is_builtin: bool = True) -> Optional[SkillInfo]:
    """从本地目录加载并解析一个 Skill。"""
    entry = os.path.basename(skill_dir)
    skill_md_path = os.path.join(skill_dir, _SKILL_MD)
    if not os.path.isfile(skill_md_path):
        logger.warning("Skill 目录 '%s' 缺少 %s，跳过", entry, _SKILL_MD)
        return None

    name, description, content = _parse_skill_md(skill_md_path)
    if name is None:
        logger.warning("Skill '%s' 的 %s 缺少有效的 front-matter，跳过", entry, _SKILL_MD)
        return None

    if name != entry:
        # M9: 技能名以 SKILL.md front-matter 的 name 为准，不再强制回落到目录名。
        # 索引键、allow_skills 绑定与 load_skill 均以此 name 为唯一标识。
        logger.warning(
            "Skill 目录 '%s' 与 front-matter name '%s' 不一致，以 front-matter name 为准",
            entry, name,
        )

    # 收集目录下的相对文件路径
    files = []
    for root, dirs, filenames in os.walk(skill_dir):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']
        for filename in filenames:
            if filename.endswith('.pyc') or filename == '.DS_Store' or filename.startswith('.'):
                continue
            abs_path = os.path.join(root, filename)
            rel_path = os.path.relpath(abs_path, skill_dir)
            files.append(rel_path)
    files.sort()

    return SkillInfo(
        name=name,
        description=description,
        content=content,
        skill_dir=skill_dir,
        is_builtin=is_builtin,
        files=files,
    )

def shutdown() -> None:
    """清理 Skill 索引。"""
    global _registry, _product_skills, _role_skills
    _registry.clear()
    _product_skills = list(_DEFAULT_PRODUCT_SKILLS)
    _role_skills = {}
    logger.info("Skill 服务已关闭")


def get_all_skills() -> list[SkillInfo]:
    """返回全量 Skill 列表。"""
    return list(_registry.values())


def get_skill(name: str) -> Optional[SkillInfo]:
    """按名称查询单个 Skill。"""
    return _registry.get(name)


def is_valid_skill(name: str) -> bool:
    """检查 Skill 名称是否存在于全局索引。"""
    return name in _registry


def _load_skill_bindings() -> None:
    """加载 assets/preset/skill_bindings.json，构建工作类型→技能绑定表。

    - product_skills：全体成员常驻技能；缺省沿用 _DEFAULT_PRODUCT_SKILLS。
    - role_skills：role_template 名 → 该岗位对口技能列表。
    对引用了不存在（未扫描到）的技能名给出告警并跳过，避免脏绑定。
    绑定表以 SKILL.md front-matter 的 name 为唯一标识（与 M9 保持一致）。
    """
    global _product_skills, _role_skills
    _product_skills = list(_DEFAULT_PRODUCT_SKILLS)
    _role_skills = {}

    path = os.path.join(appPaths.PRESET_DIR, _SKILL_BINDINGS_FILE)
    if not os.path.isfile(path):
        logger.info("未找到技能绑定表 %s，仅启用默认产品技能", path)
        return

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.error("加载技能绑定表失败 %s: %s", path, e)
        return

    raw_product = data.get("product_skills")
    if isinstance(raw_product, list):
        _product_skills = _filter_existing(raw_product, context="product_skills")

    raw_roles = data.get("role_skills") or {}
    if isinstance(raw_roles, dict):
        for role_name, skills in raw_roles.items():
            if not isinstance(skills, list):
                continue
            valid = _filter_existing(skills, context=f"role_skills[{role_name}]")
            if valid:
                _role_skills[str(role_name)] = valid

    logger.info(
        "技能绑定表加载完成：产品技能 %d 个，覆盖 %d 个岗位",
        len(_product_skills), len(_role_skills),
    )


def _filter_existing(names: list[str], context: str) -> list[str]:
    """保序去重并过滤掉索引中不存在的技能名。"""
    result: list[str] = []
    for name in names:
        name = str(name).strip()
        if not name or name in result:
            continue
        if name not in _registry:
            logger.warning("技能绑定 %s 引用了未知技能 '%s'，已跳过", context, name)
            continue
        result.append(name)
    return result


def get_product_skills() -> list[str]:
    """返回全体成员常驻的产品级技能名列表。"""
    return list(_product_skills)


def get_role_default_skills(role_template_name: str) -> list[str]:
    """返回某个 role_template（岗位/院工作类型）对口的额外技能名列表。"""
    return list(_role_skills.get(role_template_name, []))


def get_effective_skill_names(
    role_template_name: str | None = None,
    allow_skills: list[str] | None = None,
) -> list[str]:
    """汇总某成员最终可见的技能：岗位对口技能 + 团队显式授权 + 产品常驻技能。

    保序去重，且只保留索引中真实存在的技能，供 promptBuilder / load_skill 复用，
    避免各处重复硬编码产品技能列表。
    """
    merged = list(allow_skills or [])
    if role_template_name:
        merged += get_role_default_skills(role_template_name)
    merged += _product_skills
    return _filter_existing(merged, context="effective_skills")






def _parse_skill_md(path: str) -> tuple[Optional[str], str, str]:
    """解析 SKILL.md 的 YAML front-matter，返回 (name, description, content)。

    front-matter 格式::

        ---
        name: frontend-design
        description: Create distinctive...
        ---

    如果缺少 name，返回 (None, "", "")。
    如果缺少 description，默认为空字符串。
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return None, "", ""

    if not content.startswith("---"):
        return None, "", content

    # 找到 front-matter 结束标记
    end_marker = content.find("---", 3)
    if end_marker == -1:
        return None, "", content

    front_matter = content[3:end_marker].strip()
    
    try:
        parsed = yaml.safe_load(front_matter) or {}
        name = parsed.get("name")
        description = parsed.get("description", "")
        
        if name is not None:
            name = str(name).strip()
        if description is not None:
            description = str(description).strip()
            
    except Exception as e:
        logger.error("解析 YAML front-matter 失败: %s", e)
        return None, "", content

    return name, description, content