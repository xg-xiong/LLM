# -*- coding: utf-8 -*-
"""Agent 编排层。

职责：
- 维护对话历史与系统提示
- 调用 ChatClient 完成流式请求
- 在模型请求工具时执行工具、回传结果并继续追问
- 把过程以事件形式广播给任意 UI；失败时回滚半截消息

本模块不依赖 Textual / Web 框架，可直接被不同界面复用。
"""
from __future__ import annotations

import json
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from core.cancellation import CancellationToken
from core.config import AppConfig
from core.conversation import Conversation
from core.events import (
    AgentEvent,
    AssistantCompleted,
    AssistantDelta,
    EventSink,
    ToolCallFinished,
    ToolCallStarted,
    TurnFinished,
    TurnStarted,
)
from core.exceptions import AgentBusyError
from core.llm.base import ChatClient
from core.llm.openai_compat import OpenAICompatibleClient
from core.models import ToolResult, TurnResult
from core.prompts import MAX_TOOL_ROUNDS, SYSTEM_PROMPT, build_system_prompt
from core.skills import SkillRegistry
from core.tools import ToolRegistry, build_default_registry


class Agent:
    def __init__(
        self,
        config: AppConfig,
        *,
        client: ChatClient | None = None,
        registry: ToolRegistry | None = None,
        system_prompt: str = SYSTEM_PROMPT,
        max_tool_rounds: int = MAX_TOOL_ROUNDS,
        project_root: str | Path | None = None,
    ) -> None:
        self._config = config
        self._client = client or OpenAICompatibleClient(config.llm)
        root = project_root if project_root is not None else config.project_root
        self._project_root = (
            Path.cwd() if root is None else Path(root)
        ).expanduser().resolve()
        self._skills = SkillRegistry.discover(self._project_root)
        self._system_prompt = build_system_prompt(system_prompt, self._skills.skills)
        self._registry = registry or build_default_registry(config.search, self._skills)
        self._conversation = Conversation(self._system_prompt)
        self._max_tool_rounds = max_tool_rounds
        self._turn_lock = threading.Lock()

    @property
    def config(self) -> AppConfig:
        return self._config

    @property
    def project_root(self) -> Path:
        return self._project_root

    @property
    def skills(self) -> SkillRegistry:
        return self._skills

    @property
    def skill_names(self) -> list[str]:
        return self._skills.names

    @property
    def tool_names(self) -> list[str]:
        return self._registry.names

    @property
    def tool_catalog(self) -> list[tuple[str, str]]:
        return self._registry.catalog

    @property
    def history(self) -> list[dict[str, Any]]:
        return self._conversation.messages

    def clear(self) -> None:
        if self._turn_lock.locked():
            raise AgentBusyError("当前回合尚未结束，无法清空历史")
        self._conversation.clear()

    def send(
        self,
        user_text: str,
        *,
        on_event: EventSink | None = None,
        cancel: CancellationToken | None = None,
    ) -> TurnResult:
        """执行一轮对话。该方法会阻塞到本轮结束，UI 应放到工作线程。"""
        if not self._turn_lock.acquire(blocking=False):
            raise AgentBusyError("上一轮对话尚未结束")

        try:
            self._emit(on_event, TurnStarted(user_text))

            if not user_text.strip():
                result = TurnResult(ok=False, error="输入不能为空")
            else:
                self._conversation.add_user(user_text)
                # 快照包含本轮 user 消息：失败时保留提问、丢弃半截 assistant/tool
                snapshot = self._conversation.snapshot()
                try:
                    result = self._run_turn(on_event, cancel)
                except Exception as exc:  # noqa: BLE001 - 顶层兜底，避免 UI 永久忙碌
                    result = TurnResult(ok=False, error=f"内部错误: {exc}")

                if not result.ok:
                    self._conversation.restore(snapshot)

            self._emit(
                on_event,
                TurnFinished(
                    ok=result.ok,
                    content=result.content,
                    error=result.error,
                    cancelled=result.cancelled,
                ),
            )
            return result
        finally:
            self._turn_lock.release()

    def _run_turn(
        self,
        on_event: EventSink | None,
        cancel: CancellationToken | None,
    ) -> TurnResult:
        failed_tools: dict[tuple[str, str], ToolResult] = {}
        for round_index in range(self._max_tool_rounds):
            if cancel is not None and cancel.cancelled:
                return TurnResult(ok=False, cancelled=True, error="已取消")

            result = self._client.chat_stream(
                self._conversation.messages,
                self._registry.schemas(),
                on_text=lambda text, index=round_index: self._emit(
                    on_event, AssistantDelta(index, text)
                ),
                cancel=cancel,
            )
            if result.cancelled:
                return TurnResult(
                    ok=False,
                    cancelled=True,
                    error=result.error or "已取消",
                )
            if not result.ok:
                return TurnResult(ok=False, error=result.error or "请求失败")

            content = result.content
            tool_calls = list(result.tool_calls)

            self._emit(on_event, AssistantCompleted(round_index, content))

            if tool_calls:
                self._conversation.add_assistant(content, tool_calls)
                for call in tool_calls:
                    if cancel is not None and cancel.cancelled:
                        return TurnResult(ok=False, cancelled=True, error="已取消")
                    self._run_tool(round_index, call, on_event, failed_tools)
                continue

            self._conversation.add_assistant(content)
            return TurnResult(ok=True, content=content)

        return TurnResult(ok=False, error="工具调用轮次过多，本轮已停止")

    def _run_tool(
        self,
        round_index: int,
        call: Mapping[str, Any],
        on_event: EventSink | None,
        failed_tools: dict[tuple[str, str], ToolResult],
    ) -> None:
        fn = call.get("function") or {}
        name = fn.get("name", "") if isinstance(fn, Mapping) else ""
        call_id = str(call.get("id", ""))
        raw_args = fn.get("arguments") if isinstance(fn, Mapping) else None
        if not isinstance(raw_args, str):
            raw_args = json.dumps(raw_args or {}, ensure_ascii=False)

        signature = self._tool_signature(name, raw_args)
        cached = failed_tools.get(signature)
        if cached is not None:
            self._conversation.add_tool_result(
                call_id,
                f"{cached.output}\n\n"
                "[系统提示：本轮已执行过完全相同的工具调用且失败，已跳过重复执行。"
                "请勿再次调用相同工具和参数，请改用其他参数或直接向用户说明失败原因。]",
            )
            return

        self._emit(
            on_event,
            ToolCallStarted(
                round_index=round_index,
                tool_call_id=call_id,
                name=name,
                arguments=raw_args,
            ),
        )
        outcome = self._registry.dispatch(call)
        self._emit(
            on_event,
            ToolCallFinished(
                round_index=round_index,
                tool_call_id=call_id,
                name=name,
                output=outcome.output,
                is_error=outcome.is_error,
            ),
        )
        if outcome.is_error:
            failed_tools[signature] = outcome
        self._conversation.add_tool_result(call_id, outcome.output)

    @staticmethod
    def _tool_signature(name: str, raw_args: str) -> tuple[str, str]:
        try:
            parsed = json.loads(raw_args)
        except (TypeError, ValueError):
            return name, raw_args
        return name, json.dumps(
            parsed,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _emit(on_event: EventSink | None, event: AgentEvent) -> None:
        if on_event is not None:
            on_event(event)
