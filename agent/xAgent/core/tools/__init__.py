# -*- coding: utf-8 -*-
from .filesystem import build_filesystem_tools
from .registry import Tool, ToolRegistry
from .system import build_system_tools


def build_default_registry() -> ToolRegistry:
    return ToolRegistry([*build_system_tools(), *build_filesystem_tools()])


__all__ = [
    "Tool",
    "ToolRegistry",
    "build_default_registry",
    "build_filesystem_tools",
    "build_system_tools",
]
