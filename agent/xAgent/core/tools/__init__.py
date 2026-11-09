# -*- coding: utf-8 -*-
from pathlib import Path

from core.config import CLIConfig, MCPConfig, SearchConfig, WebConfig
from core.mcp import MCPManager
from core.skills import SkillRegistry

from .context import build_context_tools
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
    web_config: WebConfig | None = None,
    cli_config: CLIConfig | None = None,
) -> ToolRegistry:
    search = search_config or SearchConfig()
    skills = skill_registry if skill_registry is not None else SkillRegistry.discover()
    return ToolRegistry(
        [
            *build_system_tools(cli_config),
            *build_filesystem_tools(),
            *build_web_tools(web_config),
            *build_search_tools(search),
            *build_skill_tools(skills),
        ]
    )


def create_mcp_manager(
    project_root: str | Path,
    config: MCPConfig | None = None,
) -> MCPManager:
    """只读取 .mcp.json，不建立连接；连接由调用方在后台线程中触发。"""
    return MCPManager.from_project_root(project_root, config)


def register_mcp_tools(
    registry: ToolRegistry,
    manager: MCPManager,
) -> None:
    """把 manager 已发现的 MCP 工具注册到 registry。"""
    for tool in build_mcp_tools(manager, registry.names):
        registry.register(tool)


def connect_and_register_mcp(
    registry: ToolRegistry,
    project_root: str | Path,
    config: MCPConfig | None = None,
) -> MCPManager:
    """同步连接 MCP 并注册工具；保留给非 TUI 调用方使用。"""
    manager = create_mcp_manager(project_root, config)
    manager.connect_all()
    register_mcp_tools(registry, manager)
    return manager


__all__ = [
    "Tool",
    "ToolRegistry",
    "build_context_tools",
    "build_default_registry",
    "build_filesystem_tools",
    "build_mcp_tools",
    "build_search_tools",
    "build_skill_tools",
    "build_system_tools",
    "build_web_tools",
    "connect_and_register_mcp",
    "create_mcp_manager",
    "register_mcp_tools",
]
