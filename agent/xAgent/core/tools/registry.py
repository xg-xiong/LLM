# -*- coding: utf-8 -*-
"""工具注册表。

工具由「Schema（给模型看）+ handler（本地执行）」组成。
新增工具只需构造 Tool 并注册，Agent 与 UI 都不需要修改。
"""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from core.models import ToolResult

ToolHandler = Callable[[dict[str, Any]], str]


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    description: str
    parameters: Mapping[str, Any]
    handler: ToolHandler

    def to_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": dict(self.parameters),
            },
        }


class ToolRegistry:
    def __init__(self, tools: Sequence[Tool] = ()) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"工具重复注册: {tool.name}")
        self._tools[tool.name] = tool

    @property
    def names(self) -> list[str]:
        return list(self._tools)

    @property
    def catalog(self) -> list[tuple[str, str]]:
        return [(tool.name, tool.description) for tool in self._tools.values()]

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.to_schema() for tool in self._tools.values()]

    def dispatch(self, call: Mapping[str, Any]) -> ToolResult:
        fn = call.get("function") or {}
        name = fn.get("name", "") if isinstance(fn, Mapping) else ""
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(output=f"未知工具: {name}", is_error=True)

        raw_args = fn.get("arguments") or "{}"
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            if not isinstance(args, dict):
                raise ValueError("arguments 必须是 JSON 对象")
        except (TypeError, ValueError) as exc:
            return ToolResult(
                output=f"工具 {name} 入参解析失败: {exc}",
                is_error=True,
            )

        try:
            output = tool.handler(args)
        except Exception as exc:  # noqa: BLE001 - 工具异常不能让整个会话崩溃
            return ToolResult(output=f"工具 {name} 执行异常: {exc}", is_error=True)

        return ToolResult(output=output if isinstance(output, str) else str(output))
