# -*- coding: utf-8 -*-
"""core 向任意 UI 适配层广播的事件。

约定：core 只产生事件，不直接操作终端、网络或控件。
TUI 使用 call_from_thread 消费；未来的 Web / Desktop 适配层可以
把同一批事件映射为 WebSocket 消息、信号槽或桌面通知。
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TurnStarted:
    user_text: str


@dataclass(frozen=True, slots=True)
class AssistantDelta:
    """流式正文片段。round_index 从 0 开始，工具调用会开启新一轮。"""

    round_index: int
    text: str


@dataclass(frozen=True, slots=True)
class AssistantCompleted:
    round_index: int
    content: str


@dataclass(frozen=True, slots=True)
class ToolCallStarted:
    round_index: int
    tool_call_id: str
    name: str
    arguments: str


@dataclass(frozen=True, slots=True)
class ToolCallFinished:
    round_index: int
    tool_call_id: str
    name: str
    output: str
    is_error: bool


@dataclass(frozen=True, slots=True)
class TurnFinished:
    ok: bool
    content: str = ""
    error: str | None = None
    cancelled: bool = False


AgentEvent = (
    TurnStarted
    | AssistantDelta
    | AssistantCompleted
    | ToolCallStarted
    | ToolCallFinished
    | TurnFinished
)

EventSink = Callable[[AgentEvent], None]
