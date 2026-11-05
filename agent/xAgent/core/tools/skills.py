# -*- coding: utf-8 -*-
"""Agent Skills 加载与创建工具（loadSkill / createSkill）。"""
from __future__ import annotations

import locale
import os
from contextlib import suppress
from pathlib import Path
from typing import Any

from core.skills import (
    SKILL_FILENAME,
    SKILLS_RELATIVE_DIR,
    Skill,
    SkillDiscoveryError,
    SkillRegistry,
    validate_skill_definition,
)

from .registry import Tool


def _is_within(base: Path, target: Path) -> bool:
    try:
        target.relative_to(base)
    except ValueError:
        return False
    return True


def _relative_path(skill: Skill, path: Path) -> str:
    try:
        return path.relative_to(skill.directory).as_posix()
    except ValueError:
        return str(path)


def _decode_text(data: bytes) -> str:
    if b"\x00" in data[:4096]:
        raise ValueError("目标文件不是可读取的文本文件")

    for encoding in (
        "utf-8-sig",
        "utf-8",
        locale.getpreferredencoding(False),
        "gb18030",
    ):
        if not encoding:
            continue
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def _read_skill_file(skill: Skill, path: Path) -> str:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"读取 Skill 文件失败: {exc}") from exc

    text = _decode_text(data)
    return f"Skill: `{skill.name}`\nFile: {_relative_path(skill, path)}\n\n{text}"


def _is_bare_filename(raw: str) -> bool:
    return "/" not in raw and "\\" not in raw and ":" not in raw


def _find_by_name(skill: Skill, filename: str) -> list[Path]:
    matches: list[Path] = []
    for current, directories, files in os.walk(skill.directory, followlinks=False):
        directories[:] = sorted(directories)
        for name in sorted(files):
            if name != filename:
                continue
            candidate = (Path(current) / name).resolve()
            if _is_within(skill.directory, candidate):
                matches.append(candidate)

    unique = {str(path): path for path in matches}
    return sorted(unique.values(), key=lambda path: _relative_path(skill, path).lower())


def _format_candidates(skill: Skill, filename: str, matches: list[Path]) -> str:
    lines = [
        f"在 Skill `{skill.name}` 中找到多个名为 `{filename}` 的文件。",
        "请从以下候选中选择一个路径，并作为 filename 重新调用 loadSkill：",
    ]
    lines.extend(f"- {_relative_path(skill, path)}" for path in matches)
    return "\n".join(lines)


def _resolve_file(
    skill: Skill,
    project_root: Path,
    filename: str,
) -> tuple[Path | None, list[Path]]:
    raw = filename.strip()
    candidate = Path(raw).expanduser()

    if candidate.is_absolute():
        resolved = candidate.resolve()
        if not _is_within(skill.directory, resolved):
            raise ValueError("filename 超出指定 Skill 目录，禁止读取")
        if resolved.is_file():
            return resolved, []
        if resolved.exists():
            raise ValueError(f"filename 指向的不是文件: {resolved}")
        raise ValueError(f"文件不存在: {resolved}")

    skill_relative = (skill.directory / candidate).resolve()
    if skill_relative.exists():
        if not _is_within(skill.directory, skill_relative):
            raise ValueError("filename 超出指定 Skill 目录，禁止读取")
        if skill_relative.is_file():
            return skill_relative, []
        raise ValueError(f"filename 指向的不是文件: {skill_relative}")

    project_relative = (project_root / candidate).resolve()
    if project_relative.exists():
        if not _is_within(skill.directory, project_relative):
            raise ValueError("filename 超出指定 Skill 目录，禁止读取")
        if project_relative.is_file():
            return project_relative, []
        raise ValueError(f"filename 指向的不是文件: {project_relative}")

    if _is_bare_filename(raw):
        matches = _find_by_name(skill, raw)
        if len(matches) == 1:
            return matches[0], []
        if len(matches) > 1:
            return None, matches

    raise ValueError(f"在 Skill `{skill.name}` 中未找到文件: {raw}")


def load_skill(args: dict[str, Any], skills: SkillRegistry) -> str:
    if not isinstance(args, dict):
        raise ValueError("loadSkill 参数必须是对象")

    name = args.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("缺少参数 name 或 name 不是非空字符串")
    name = name.strip()

    skill = skills.get(name)
    if skill is None:
        available = ", ".join(f"`{item}`" for item in skills.names) or "无"
        raise ValueError(f"未找到 Skill {name!r}。可用 Skill: {available}")

    filename = args.get("filename")
    if filename is None or (isinstance(filename, str) and not filename.strip()):
        return _read_skill_file(skill, skill.skill_file)
    if not isinstance(filename, str):
        raise ValueError("filename 必须是字符串")

    path, matches = _resolve_file(skill, skills.project_root, filename)
    if path is None:
        return _format_candidates(skill, filename.strip(), matches)
    return _read_skill_file(skill, path)


def create_skill(args: dict[str, Any], skills: SkillRegistry) -> str:
    if not isinstance(args, dict):
        raise ValueError("createSkill 参数必须是对象")

    name = args.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("缺少参数 name 或 name 不是非空字符串")
    name = name.strip()

    skill_context = args.get("skillContext")
    if not isinstance(skill_context, str) or not skill_context.strip():
        raise ValueError("缺少参数 skillContext 或 skillContext 不是非空字符串")

    try:
        content, description = validate_skill_definition(name, skill_context)
    except SkillDiscoveryError as exc:
        raise ValueError(f"skillContext 不符合 Agent Skills 规范: {exc}") from exc

    existing = skills.get(name)
    if existing is not None:
        return (
            f"Skill `{name}` 已存在，未覆盖原有内容。"
            f"现有位置: {existing.skill_file}"
        )

    skills_root = skills.project_root / SKILLS_RELATIVE_DIR
    target_directory = skills_root / name
    if target_directory.exists():
        return (
            f"Skill `{name}` 的目标目录已存在，未覆盖原有内容: "
            f"{target_directory}"
        )

    try:
        target_directory.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        return (
            f"Skill `{name}` 的目标目录已存在，未覆盖原有内容: "
            f"{target_directory}"
        )
    except OSError as exc:
        raise ValueError(f"创建 Skill 目录失败: {exc}") from exc

    skill_file = target_directory / SKILL_FILENAME
    try:
        with skill_file.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
    except FileExistsError:
        with suppress(OSError):
            target_directory.rmdir()
        return f"Skill `{name}` 的 SKILL.md 已存在，未覆盖原有内容: {skill_file}"
    except OSError as exc:
        with suppress(OSError):
            skill_file.unlink()
        with suppress(OSError):
            target_directory.rmdir()
        raise ValueError(f"写入 SKILL.md 失败: {exc}") from exc

    skill = Skill(
        name=name,
        description=description,
        directory=target_directory.resolve(),
        skill_file=skill_file.resolve(),
    )
    skills.add(skill)
    return (
        f"已创建 Skill `{name}`：\n"
        f"- 目录: {skill.directory}\n"
        f"- 文件: {skill.skill_file}\n"
        "SKILL.md 已通过 Frontmatter 校验。若还需要 references/、scripts/ 等目录或文件，"
        "请继续调用 createDirectory、createFile 等 fileOps 工具。"
    )


def build_skill_tools(skills: SkillRegistry) -> list[Tool]:
    def load_handler(args: dict[str, Any]) -> str:
        return load_skill(args, skills)

    def create_handler(args: dict[str, Any]) -> str:
        return create_skill(args, skills)

    return [
        Tool(
            name="loadSkill",
            description=(
                "加载 Agent Skill 的完整内容。只提供 name 时返回该 Skill 的 SKILL.md 全文；"
                "同时提供 filename 时只返回指定附件文件。filename 支持相对于 Skill 目录、"
                "项目根目录或绝对路径；只提供文件名时会在该 Skill 目录内递归查找，"
                "若有多个同名文件则返回候选路径。文件读取限制在指定 Skill 目录内。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "要加载的 Skill 名称",
                    },
                    "filename": {
                        "type": "string",
                        "description": (
                            "可选。Skill 附件路径或文件名；省略时加载 SKILL.md"
                        ),
                    },
                },
                "required": ["name"],
            },
            handler=load_handler,
        ),
        Tool(
            name="createSkill",
            description=(
                "根据用户要求创建新的 Agent Skill。name 必须由小写字母、数字和连字符组成；"
                "skillContext 必须是完整的 SKILL.md 内容，包含 YAML Frontmatter"
                "（name 与参数一致、description）及正文。工具在项目根目录的 "
                ".agents/skills/<name>/SKILL.md 写入内容；目标已存在时不会覆盖。"
                "如需 references/、scripts/ 等辅助文件，请继续调用文件工具。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": (
                            "Skill 名称，只能使用小写字母、数字和连字符，例如 pdf-tools"
                        ),
                    },
                    "skillContext": {
                        "type": "string",
                        "description": (
                            "完整的 SKILL.md 内容，必须包含 YAML Frontmatter、"
                            "与 name 一致的 name 字段、description 字段和正文"
                        ),
                    },
                },
                "required": ["name", "skillContext"],
            },
            handler=create_handler,
        ),
    ]


__all__ = ["build_skill_tools", "create_skill", "load_skill"]
