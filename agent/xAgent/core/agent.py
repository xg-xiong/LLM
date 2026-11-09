# -*- coding: utf-8 -*-
"""Agent 编排层。

职责：
- 维护对话历史与系统提示
- 调用 ChatClient 完成流式请求
- 在模型请求工具时执行工具、回传结果并继续追问
- 把过程以事件形式广播给任意 UI；失败时回滚半截消息
- 保存 / 恢复会话，并在会话首次加载时注入 AGENTS.md

本模块不依赖 Textual / Web 框架，可直接被不同界面复用。
"""
from __future__ import annotations

import json
import threading
from collections.abc import Mapping
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from core.cancellation import CancellationToken
from core.config import AppConfig
from core.context import (
    ContextManager,
    ContextStatus,
    estimate_text_tokens,
    format_transcript,
)
from core.conversation import Conversation
from core.events import (
    AgentEvent,
    AssistantCompleted,
    AssistantDelta,
    CompactionFinished,
    CompactionStarted,
    ContextUsageUpdated,
    EventSink,
    ToolCallFinished,
    ToolCallStarted,
    TurnFinished,
    TurnStarted,
)
from core.exceptions import AgentBusyError
from core.llm.base import ChatClient
from core.llm.openai_compat import OpenAICompatibleClient
from core.mcp import MCPManager, MCPServerStatus
from core.models import ToolResult, TurnResult
from core.prompts import COMPACTION_SYSTEM_PROMPT, SYSTEM_PROMPT, build_system_prompt
from core.session import SessionStore, make_title
from core.skills import SkillRegistry
from core.tools import (
    ToolRegistry,
    build_context_tools,
    build_default_registry,
    create_mcp_manager,
    register_mcp_tools,
)

_AGENTS_MD_MARKER = "[项目说明 AGENTS.md]"


class Agent:
    def __init__(
        self,
        config: AppConfig,
        *,
        client: ChatClient | None = None,
        registry: ToolRegistry | None = None,
        system_prompt: str = SYSTEM_PROMPT,
        max_tool_rounds: int | None = None,
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
        self._registry = registry or build_default_registry(
            config.search,
            self._skills,
            config.web,
            config.cli,
        )
        self._mcp: MCPManager | None = None
        if registry is None:
            self._mcp = create_mcp_manager(self._project_root, config.mcp)
        self._context = ContextManager(
            self._project_root,
            window_tokens=config.llm.context_window,
            warning_ratio=config.context.warning_ratio,
            archive_dir=config.context.archive_dir,
            max_hits=config.context.max_recall_hits,
            max_result_chars=config.context.max_recall_result_chars,
            snippet_padding=config.context.snippet_padding,
        )
        if "recallContext" not in self._registry.names:
            for tool in build_context_tools(self._context):
                self._registry.register(tool)
        self._refresh_tool_tokens()
        self._conversation = Conversation(self._system_prompt)
        self._max_tool_rounds = (
            config.max_tool_rounds if max_tool_rounds is None else max_tool_rounds
        )
        self._turn_lock = threading.Lock()

        self._session_store = SessionStore(
            self._project_root,
            config.session.directory,
        )
        self._session_id = self._session_store.new_id()
        self._session_created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._session_updated_at = self._session_created_at
        self._session_turn_count = 0
        self._session_touched = False
        self._session_error: str | None = None
        self._agents_md_injected = False
        self._mcp_connected = self._mcp is None
        self._session_lock = threading.Lock()
        self._inject_agents_md()

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
    def mcp_issues(self) -> list[str]:
        return self._mcp.issues if self._mcp is not None else []

    @property
    def mcp_server_names(self) -> list[str]:
        return self._mcp.server_names if self._mcp is not None else []

    @property
    def history(self) -> list[dict[str, Any]]:
        return self._conversation.messages

    @property
    def context_status(self) -> ContextStatus:
        return self._context.status(self._conversation.messages)

    @property
    def needs_compaction(self) -> bool:
        return self.context_status.warning

    def clear(self) -> None:
        if self._turn_lock.locked():
            raise AgentBusyError("当前回合尚未结束，无法清空历史")
        self._conversation.clear()
        self._context.reset_api_usage()
        self._agents_md_injected = False
        self._inject_agents_md()

    def close(self) -> None:
        """关闭 MCP 连接等外部资源。"""
        if self._mcp is not None:
            self._mcp.close()

    @property
    def mcp_statuses(self) -> tuple[MCPServerStatus, ...]:
        return self._mcp.statuses if self._mcp is not None else ()

    @property
    def mcp_servers(self) -> tuple[str, ...]:
        return tuple(self._mcp.server_names) if self._mcp is not None else ()

    def connect_mcp(self) -> list[str]:
        """连接 MCP 并注册新发现的工具。阻塞调用，TUI 应放到后台线程。"""
        if self._mcp is None or self._mcp_connected:
            return self.mcp_issues
        self._mcp.connect_all()
        with self._turn_lock:
            register_mcp_tools(self._registry, self._mcp)
            self._refresh_tool_tokens()
            self._mcp_connected = True
        return self.mcp_issues

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def session_path(self) -> Path:
        return self._session_store.session_path(self._session_id) / "session.json"

    @property
    def session_title(self) -> str:
        return make_title(self._conversation.messages)

    @property
    def session_error(self) -> str | None:
        return self._session_error

    @property
    def session_turn_count(self) -> int:
        return self._session_turn_count

    @property
    def has_session_content(self) -> bool:
        return self._session_touched

    def list_sessions(self):
        return self._session_store.list()

    def save_session(self) -> Path:
        """把当前会话快照和事件写入磁盘；失败时抛出 OSError。"""
        with self._session_lock:
            self._session_updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            path = self._session_store.save(
                self._session_id,
                messages=self._conversation.messages,
                created_at=self._session_created_at,
                updated_at=self._session_updated_at,
                title=self.session_title,
                turn_count=self._session_turn_count,
                agents_md_injected=self._agents_md_injected,
            )
            self._session_error = None
            return path

    def start_new_session(self, *, save_current: bool = True) -> str:
        """保存当前会话（如有内容）并开始一个全新会话。"""
        if not self._turn_lock.acquire(blocking=False):
            raise AgentBusyError("当前回合尚未结束，无法新建会话")
        try:
            if save_current:
                self._try_autosave(force=True)
            self._conversation.clear()
            self._context.reset_api_usage()
            self._session_id = self._session_store.new_id()
            self._session_created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._session_updated_at = self._session_created_at
            self._session_turn_count = 0
            self._session_touched = False
            self._session_error = None
            self._agents_md_injected = False
            self._inject_agents_md()
            return self._session_id
        finally:
            self._turn_lock.release()

    def load_session(self, session_id: str, *, save_current: bool = True) -> str:
        """恢复指定会话；返回会话标题。"""
        if not self._turn_lock.acquire(blocking=False):
            raise AgentBusyError("当前回合尚未结束，无法切换会话")
        try:
            if save_current:
                self._try_autosave(force=True)
            data = self._session_store.load(session_id)
            messages = data["messages"]
            self._conversation.replace_messages(messages)
            self._session_id = str(data.get("id") or session_id)
            self._session_created_at = str(data.get("created_at") or "")
            self._session_updated_at = str(data.get("updated_at") or "")
            self._session_turn_count = int(data.get("turn_count") or 0)
            self._session_touched = True
            self._agents_md_injected = bool(data.get("agents_md_injected")) or (
                self._has_agents_md_message()
            )
            self._context.reset_api_usage()
            if not self._agents_md_injected:
                self._inject_agents_md()
            self._append_session_event(
                "session_resumed",
                {"session_id": self._session_id},
            )
            self._try_autosave(force=True)
            return self.session_title
        finally:
            self._turn_lock.release()

    def _refresh_tool_tokens(self) -> None:
        self._context.set_tool_tokens(
            estimate_text_tokens(
                json.dumps(self._registry.schemas(), ensure_ascii=False)
            )
        )

    def _agents_md_path(self) -> Path:
        return self._project_root / "AGENTS.md"

    def _has_agents_md_message(self) -> bool:
        return any(
            message.get("role") == "system"
            and isinstance(message.get("content"), str)
            and message["content"].startswith(_AGENTS_MD_MARKER)
            for message in self._conversation.messages
        )

    def _inject_agents_md(self) -> None:
        path = self._agents_md_path()
        if not path.is_file():
            return
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError as exc:
            self._session_error = f"读取 {path} 失败: {exc}"
            return
        if not text.strip():
            return
        self._conversation.add_system(
            f"{_AGENTS_MD_MARKER}\n\n{text.strip()}"
        )
        self._agents_md_injected = True
        self._append_session_event(
            "agents_md_injected",
            {"path": str(path), "chars": len(text)},
        )

    def _try_autosave(self, *, force: bool) -> None:
        if not force and not self._config.session.auto_save:
            return
        if not self._session_touched:
            return
        try:
            self.save_session()
        except (OSError, ValueError) as exc:
            self._session_error = str(exc)

    def _append_session_event(
        self,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        try:
            self._session_store.append_event(
                self._session_id,
                event_type,
                payload,
            )
        except (OSError, ValueError):
            pass

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
                status = self.context_status
                if status.warning:
                    result = TurnResult(
                        ok=False,
                        error=self._compaction_required_message(status),
                    )
                else:
                    self._conversation.add_user(user_text)
                    self._session_touched = True
                    self._session_turn_count += 1
                    self._context.reset_api_usage()
                    # 快照包含本轮 user 消息：失败时保留提问、丢弃半截 assistant/tool
                    snapshot = self._conversation.snapshot()
                    try:
                        result = self._run_turn(on_event, cancel)
                    except Exception as exc:  # noqa: BLE001 - 顶层兜底，避免 UI 永久忙碌
                        result = TurnResult(ok=False, error=f"内部错误: {exc}")

                    if not result.ok:
                        self._conversation.restore(snapshot)
                        self._context.reset_api_usage()

            self._emit_context_usage(on_event)
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
        round_index = 0
        while self._max_tool_rounds <= 0 or round_index < self._max_tool_rounds:
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

            self._context.note_api_usage(result.usage)
            content = result.content
            tool_calls = list(result.tool_calls)

            self._emit(on_event, AssistantCompleted(round_index, content))

            if tool_calls:
                self._conversation.add_assistant(content, tool_calls)
                for call in tool_calls:
                    if cancel is not None and cancel.cancelled:
                        return TurnResult(ok=False, cancelled=True, error="已取消")
                    self._run_tool(round_index, call, on_event, failed_tools)
                self._emit_context_usage(on_event)
                round_index += 1
                continue

            self._conversation.add_assistant(content)
            self._emit_context_usage(on_event)
            return TurnResult(ok=True, content=content)

        return TurnResult(
            ok=False,
            error=(
                f"工具调用轮次已达到上限（{self._max_tool_rounds}），本次停止。"
                "可在 config.ini 的 [agent] max_tool_rounds 调大该值，或设为 0 取消限制。"
            ),
        )

    def compact(
        self,
        *,
        on_event: EventSink | None = None,
        cancel: CancellationToken | None = None,
    ) -> TurnResult:
        """手动压缩上下文：先归档原文，再调用 LLM 生成摘要并替换历史。"""
        if not self._turn_lock.acquire(blocking=False):
            raise AgentBusyError("当前回合尚未结束，无法压缩上下文")

        archive_id = ""
        timestamp_text = ""
        original_text = ""
        try:
            messages = self._conversation.snapshot()
            if len(messages) <= 1:
                return self._fail_compaction(
                    on_event,
                    archive_id="",
                    timestamp_text="",
                    original_text="",
                    error="当前没有可压缩的对话历史。",
                )

            now = datetime.now()
            archive_id = self._context.new_archive_id(now)
            timestamp_text = now.strftime("%Y-%m-%d %H:%M:%S")
            original_text = format_transcript(messages)

            self._emit(on_event, CompactionStarted(archive_id))
            try:
                self._context.save_archive(messages, archive_id)
            except OSError as exc:
                return self._fail_compaction(
                    on_event,
                    archive_id,
                    timestamp_text,
                    original_text,
                    f"保存原始上下文失败：{exc}",
                )

            result = self._summarize(messages, cancel)
            if result.cancelled:
                return self._fail_compaction(
                    on_event,
                    archive_id,
                    timestamp_text,
                    original_text,
                    result.error or "已取消",
                )
            if not result.ok:
                return self._fail_compaction(
                    on_event,
                    archive_id,
                    timestamp_text,
                    original_text,
                    result.error or "摘要生成失败",
                )

            summary = result.content.strip()
            if not summary:
                return self._fail_compaction(
                    on_event,
                    archive_id,
                    timestamp_text,
                    original_text,
                    "模型返回了空摘要，原有上下文已保留。",
                )

            note = (
                f"此前上下文已于 {timestamp_text} 完成压缩，"
                f"原始上下文保存在编号为 {archive_id} 的归档文件中。"
                "如需查找历史信息，请使用 recallContext 工具。"
            )
            final_summary = f"{summary}\n\n---\n\n{note}"

            self._conversation.replace_with_summary(final_summary)
            self._context.reset_api_usage()
            self._emit_context_usage(on_event)
            self._emit(
                on_event,
                CompactionFinished(
                    ok=True,
                    archive_id=archive_id,
                    summary=final_summary,
                    original_text=original_text,
                    timestamp=timestamp_text,
                ),
            )
            return TurnResult(ok=True, content=final_summary)
        except Exception as exc:  # noqa: BLE001 - 压缩失败必须保留原上下文
            return self._fail_compaction(
                on_event,
                archive_id,
                timestamp_text,
                original_text,
                f"压缩失败：{exc}",
            )
        finally:
            self._turn_lock.release()

    def _summarize(
        self,
        messages: list[dict[str, Any]],
        cancel: CancellationToken | None,
    ):
        system_content = ""
        if messages and isinstance(messages[0].get("content"), str):
            system_content = messages[0]["content"]

        summary_messages = [
            {
                "role": "system",
                "content": (
                    COMPACTION_SYSTEM_PROMPT
                    + "\n\n---\n以下是当前会话的原始 System Prompt"
                    "（仅用于理解，不要复述）：\n"
                    + system_content
                ),
            },
            *[dict(message) for message in messages[1:]],
        ]
        # 压缩阶段不传入任何工具定义，确保模型只能生成摘要。
        return self._client.chat_stream(
            summary_messages,
            (),
            on_text=lambda _text: None,
            cancel=cancel,
        )

    def _fail_compaction(
        self,
        on_event: EventSink | None,
        archive_id: str,
        timestamp_text: str,
        original_text: str,
        error: str,
    ) -> TurnResult:
        self._emit(
            on_event,
            CompactionFinished(
                ok=False,
                archive_id=archive_id,
                original_text=original_text,
                timestamp=timestamp_text,
                error=error,
            ),
        )
        return TurnResult(ok=False, error=error)

    @staticmethod
    def _compaction_required_message(status: ContextStatus) -> str:
        return (
            f"当前上下文已使用 {status.used_tokens:,} / {status.window_tokens:,} tokens"
            f"（{status.ratio:.0%}），已达到压缩阈值。"
            "请先执行 /compact 压缩上下文，完成后再继续输入。"
        )

    def _emit_context_usage(self, on_event: EventSink | None) -> None:
        if on_event is None:
            return
        status = self.context_status
        self._emit(
            on_event,
            ContextUsageUpdated(
                used_tokens=status.used_tokens,
                window_tokens=status.window_tokens,
                ratio=status.ratio,
                warning=status.warning,
                default_window=status.default_window,
            ),
        )

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

    def _emit(self, on_event: EventSink | None, event: AgentEvent) -> None:
        if not isinstance(event, (AssistantDelta, ContextUsageUpdated)):
            payload = asdict(event)
            self._append_session_event(type(event).__name__, payload)
        if isinstance(event, (TurnFinished, CompactionFinished)):
            self._try_autosave(force=False)
        if on_event is not None:
            on_event(event)
