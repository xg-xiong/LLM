# -*- coding: utf-8 -*-
"""与界面无关的领域模型。

模型只描述数据，不依赖 requests、Textual 等任何具体实现，
以便 TUI / Web / Desktop 等适配层共享同一套 core。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ToolResult:
    """一次工具调用的执行结果。"""

    output: str
    is_error: bool = False


@dataclass(frozen=True, slots=True)
class ChatResult:
    """一次 LLM 请求（可能包含流式文本）的结果。"""

    ok: bool
    content: str = ""
    tool_calls: tuple[dict[str, Any], ...] = ()
    error: str | None = None
    cancelled: bool = False


@dataclass(frozen=True, slots=True)
class TurnResult:
    """一轮用户提问的最终结果。"""

    ok: bool
    content: str = ""
    error: str | None = None
    cancelled: bool = False