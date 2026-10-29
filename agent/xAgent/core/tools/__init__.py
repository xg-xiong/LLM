# -*- coding: utf-8 -*-
from core.config import SearchConfig

from .filesystem import build_filesystem_tools
from .registry import Tool, ToolRegistry
from .search import build_search_tools
from .system import build_system_tools
from .web import build_web_tools


def build_default_registry(search_config: SearchConfig | None = None) -> ToolRegistry:
    config = search_config or SearchConfig()
    return ToolRegistry(
        [
            *build_system_tools(),
            *build_filesystem_tools(),
            *build_web_tools(),
            *build_search_tools(config),
        ]
    )


__all__ = [
    "Tool",
    "ToolRegistry",
    "build_default_registry",
    "build_filesystem_tools",
    "build_search_tools",
    "build_system_tools",
    "build_web_tools",
]
