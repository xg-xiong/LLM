# -*- coding: utf-8 -*-
"""Agent Skills 发现与元数据注册。

项目根目录默认为程序启动时的工作目录，Skill 放在：
    <project_root>/.agents/skills/<skill_name>/SKILL.md

初始化阶段只读取 SKILL.md 的 YAML Frontmatter，不读取正文。
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

SKILLS_RELATIVE_DIR = Path(".agents") / "skills"
SKILL_FILENAME = "SKILL.md"
MAX_SKILL_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024
MAX_FRONTMATTER_CHARS = 64_000

_SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class SkillDiscoveryError(Exception):
    """单个 Skill 无法被发现或解析。"""


@dataclass(frozen=True, slots=True)
class Skill:
    name: str
    description: str
    directory: Path
    skill_file: Path


@dataclass(frozen=True, slots=True)
class SkillIssue:
    directory: Path
    message: str


class SkillRegistry:
    def __init__(
        self,
        project_root: Path,
        skills: Sequence[Skill] = (),
        issues: Sequence[SkillIssue] = (),
    ) -> None:
        self.project_root = project_root.resolve()
        self._skills = tuple(skills)
        self._by_name = {skill.name: skill for skill in skills}
        self.issues = tuple(issues)

    @property
    def skills(self) -> tuple[Skill, ...]:
        return self._skills

    @property
    def names(self) -> list[str]:
        return [skill.name for skill in self._skills]

    def get(self, name: str) -> Skill | None:
        return self._by_name.get(name)

    @classmethod
    def discover(cls, project_root: str | Path | None = None) -> SkillRegistry:
        root = Path.cwd() if project_root is None else Path(project_root)
        root = root.expanduser().resolve()
        skills_root = root / SKILLS_RELATIVE_DIR
        if not skills_root.is_dir():
            return cls(root)

        try:
            directories = sorted(
                (entry for entry in skills_root.iterdir() if entry.is_dir()),
                key=lambda entry: entry.name.lower(),
            )
        except OSError as exc:
            return cls(
                root,
                issues=(SkillIssue(skills_root, f"无法扫描 skills 目录: {exc}"),),
            )

        skills: list[Skill] = []
        issues: list[SkillIssue] = []
        seen: dict[str, Skill] = {}
        for directory in directories:
            try:
                skill = _load_skill_metadata(directory)
            except SkillDiscoveryError as exc:
                issues.append(SkillIssue(directory, str(exc)))
                continue

            previous = seen.get(skill.name)
            if previous is not None:
                issues.append(
                    SkillIssue(
                        directory,
                        f"重复的 skill name {skill.name!r}，已使用 {previous.directory}",
                    )
                )
                continue

            seen[skill.name] = skill
            skills.append(skill)

        return cls(root, skills, issues)


def _read_frontmatter(skill_file: Path) -> str:
    try:
        with skill_file.open("r", encoding="utf-8-sig") as handle:
            first_line = handle.readline()
            if first_line.strip() != "---":
                raise SkillDiscoveryError("SKILL.md 必须以 YAML Frontmatter (`---`) 开头")

            lines: list[str] = []
            total = 0
            for line in handle:
                total += len(line)
                if total > MAX_FRONTMATTER_CHARS:
                    raise SkillDiscoveryError(
                        f"YAML Frontmatter 超过 {MAX_FRONTMATTER_CHARS} 个字符"
                    )
                if line.strip() in {"---", "..."}:
                    if not lines:
                        raise SkillDiscoveryError("YAML Frontmatter 不能为空")
                    return "".join(lines)
                lines.append(line)
    except UnicodeDecodeError as exc:
        raise SkillDiscoveryError("SKILL.md 不是有效的 UTF-8 文本") from exc
    except OSError as exc:
        raise SkillDiscoveryError(f"无法读取 SKILL.md: {exc}") from exc

    raise SkillDiscoveryError("YAML Frontmatter 缺少结束分隔符 `---`")


def _load_skill_metadata(directory: Path) -> Skill:
    skill_file = directory / SKILL_FILENAME
    if not skill_file.is_file():
        raise SkillDiscoveryError(f"缺少 {SKILL_FILENAME}")

    frontmatter = _read_frontmatter(skill_file)
    try:
        data = yaml.safe_load(frontmatter)
    except yaml.YAMLError as exc:
        raise SkillDiscoveryError(f"YAML Frontmatter 解析失败: {exc}") from exc

    if not isinstance(data, dict):
        raise SkillDiscoveryError("YAML Frontmatter 必须是对象")

    name = data.get("name")
    description = data.get("description")
    if not isinstance(name, str) or not name.strip():
        raise SkillDiscoveryError("YAML Frontmatter 缺少非空字符串字段 name")
    if not isinstance(description, str) or not description.strip():
        raise SkillDiscoveryError("YAML Frontmatter 缺少非空字符串字段 description")

    name = name.strip()
    description = description.strip()
    if len(name) > MAX_SKILL_NAME_LENGTH:
        raise SkillDiscoveryError(f"skill name 超过 {MAX_SKILL_NAME_LENGTH} 个字符")
    if not _SKILL_NAME_RE.fullmatch(name):
        raise SkillDiscoveryError(
            "skill name 只能包含小写字母、数字和连字符，且不能以连字符开头或结尾"
        )
    if len(description) > MAX_DESCRIPTION_LENGTH:
        raise SkillDiscoveryError(f"description 超过 {MAX_DESCRIPTION_LENGTH} 个字符")

    resolved_directory = directory.resolve()
    resolved_skill_file = skill_file.resolve()
    try:
        resolved_skill_file.relative_to(resolved_directory)
    except ValueError as exc:
        raise SkillDiscoveryError("SKILL.md 必须位于 Skill 目录内部") from exc

    return Skill(
        name=name,
        description=description,
        directory=resolved_directory,
        skill_file=resolved_skill_file,
    )


__all__ = [
    "SKILLS_RELATIVE_DIR",
    "SKILL_FILENAME",
    "Skill",
    "SkillDiscoveryError",
    "SkillIssue",
    "SkillRegistry",
]
