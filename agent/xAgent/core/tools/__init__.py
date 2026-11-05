# -*- coding: utf-8 -*-
from pathlib import Path

from core.config import SearchConfig
from core.mcp import MCPManager
from core.skills import SkillRegistry

from .filesystem import build_filesystem_tools
from .mcp import build_mcp_tools
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


def register_mcp_tools(
    registry: ToolRegistry,
    project_root: str | Path,
) -> MCPManager:
    """读取项目目录的 .mcp.json 并把 MCP 工具注册到 registry。"""
    manager = MCPManager.from_project_root(project_root)
    manager.connect_all()
    for tool in build_mcp_tools(manager, registry.names):
        registry.register(tool)
    return manager


__all__ = [
    "Tool",
    "ToolRegistry",
    "build_default_registry",
    "build_filesystem_tools",
    "build_mcp_tools",
    "build_search_tools",
    "build_skill_tools",
    "build_system_tools",
    "build_web_tools",
    "register_mcp_tools",
]
