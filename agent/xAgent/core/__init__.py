# -*- coding: utf-8 -*-
"""xAgent 的界面无关核心层。

对外只暴露 Agent、配置、事件与领域模型；具体 UI（tui / web / desktop）
通过 Agent.send(on_event=...) 订阅过程事件。
"""
from .agent import Agent
from .cancellation import CancellationToken
from .config import AppConfig, LLMConfig, SearchConfig
from .events import (
    AgentEvent,
    AssistantCompleted,
    AssistantDelta,
    ToolCallFinished,
    ToolCallStarted,
    TurnFinished,
    TurnStarted,
)
from .exceptions import AgentBusyError, AgentError
from .models import ChatResult, ToolResult, TurnResult
from .prompts import MAX_TOOL_ROUNDS, SYSTEM_PROMPT

__all__ = [
    "MAX_TOOL_ROUNDS",
    "SYSTEM_PROMPT",
    "Agent",
    "AgentBusyError",
    "AgentError",
    "AgentEvent",
    "AppConfig",
    "AssistantCompleted",
    "AssistantDelta",
    "CancellationToken",
    "ChatResult",
    "LLMConfig",
    "SearchConfig",
    "ToolCallFinished",
    "ToolCallStarted",
    "ToolResult",
    "TurnFinished",
    "TurnResult",
    "TurnStarted",
]
