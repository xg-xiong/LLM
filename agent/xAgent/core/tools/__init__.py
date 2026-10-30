# -*- coding: utf-8 -*-
from core.config import SearchConfig
from core.skills import SkillRegistry

from .filesystem import build_filesystem_tools
from .registry import Tool, ToolRegistry
from .search import build_search_tools
from .skills import build_skill_tools
from .system import build_system_tools
from .web import build_web_tools


def build_default_registry(
    search_config: SearchConfig | None = None,
    skill_registry: SkillRegistry | None = None,
) -> ToolRegistry:
    config = search_config or SearchConfig()
    skills = skill_registry if skill_registry is not None else SkillRegistry.discover()
    return ToolRegistry(
        [
            *build_system_tools(),
            *build_filesystem_tools(),
            *build_web_tools(),
            *build_search_tools(config),
            *build_skill_tools(skills),
        ]
    )


__all__ = [
    "Tool",
    "ToolRegistry",
    "build_default_registry",
    "build_filesystem_tools",
    "build_search_tools",
    "build_skill_tools",
    "build_system_tools",
    "build_web_tools",
]
