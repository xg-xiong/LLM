# -*- coding: utf-8 -*-
"""xAgent 的界面无关核心层。

对外只暴露 Agent、配置、事件与领域模型；具体 UI（tui / web / desktop）
通过 Agent.send(on_event=...) 订阅过程事件。
"""
from .agent import Agent
from .cancellation import CancellationToken
from .config import (
    AppConfig,
    CLIConfig,
    ContextConfig,
    LLMConfig,
    MCPConfig,
    SearchConfig,
    SessionConfig,
    WebConfig,
)
from .context import ContextStatus
from .events import (
    AgentEvent,
    AssistantCompleted,
    AssistantDelta,
    CompactionFinished,
    CompactionStarted,
    ContextUsageUpdated,
    ToolCallFinished,
    ToolCallStarted,
    TurnFinished,
    TurnStarted,
)
from .exceptions import AgentBusyError, AgentError
from .mcp import MCPServerStatus
from .models import ChatResult, TokenUsage, ToolResult, TurnResult
from .prompts import MAX_TOOL_ROUNDS, SYSTEM_PROMPT
from .session import SessionInfo, SessionStore
from .skills import Skill, SkillRegistry

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
    "CLIConfig",
    "CancellationToken",
    "ChatResult",
    "CompactionFinished",
    "CompactionStarted",
    "ContextConfig",
    "ContextStatus",
    "ContextUsageUpdated",
    "LLMConfig",
    "MCPConfig",
    "MCPServerStatus",
    "SearchConfig",
    "SessionConfig",
    "SessionInfo",
    "SessionStore",
    "Skill",
    "SkillRegistry",
    "WebConfig",
    "TokenUsage",
    "ToolCallFinished",
    "ToolCallStarted",
    "ToolResult",
    "TurnFinished",
    "TurnResult",
    "TurnStarted",
]
