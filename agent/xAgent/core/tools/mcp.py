# -*- coding: utf-8 -*-
"""把 MCP Server 发现的工具注册进 xAgent 工具注册表。"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from core.mcp import MCPManager, unique_tool_name
from core.models import ToolResult

from .registry import Tool


def _make_handler(manager: MCPManager, exposed_name: str):
    def handler(args: dict[str, Any]) -> ToolResult:
        return manager.call_tool(exposed_name, args)

    return handler


def build_mcp_tools(
    manager: MCPManager,
    existing_names: Iterable[str] = (),
) -> list[Tool]:
    """为 manager 中的全部 MCP 工具创建 Tool，并登记名称映射。"""
    used = set(existing_names)
    tools: list[Tool] = []
    for spec in manager.tools:
        exposed_name = unique_tool_name(spec, used)
        used.add(exposed_name)
        manager.bind_tool(exposed_name, spec)

        description = spec.description.strip() or (
            f"MCP 工具 {spec.server}/{spec.name}"
        )
        tools.append(
            Tool(
                name=exposed_name,
                description=f"[MCP Server: {spec.server}] {description}",
                parameters=dict(spec.parameters),
                handler=_make_handler(manager, exposed_name),
            )
        )
    return tools


__all__ = ["build_mcp_tools"]
