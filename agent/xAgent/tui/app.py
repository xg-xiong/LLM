# -*- coding: utf-8 -*-
"""Textual 适配层。

该文件是 core 与具体 UI 的唯一耦合点：
- 把 Agent 事件映射为控件更新
- 把键盘 / 输入框操作映射为 Agent 调用
新增 Web / Desktop 界面时，不需要改动 core，只需新增类似的适配层。
"""
from __future__ import annotations

import json
import secrets
from contextlib import suppress
from pathlib import Path
from time import perf_counter
from typing import ClassVar

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, HorizontalGroup, VerticalGroup, VerticalScroll
from textual.widgets import Input, Static

from core import (
    Agent,
    AgentBusyError,
    AppConfig,
    AssistantCompleted,
    AssistantDelta,
    CancellationToken,
    ToolCallFinished,
    ToolCallStarted,
    TurnFinished,
    TurnStarted,
)

from .widgets import ChatLog, TopBar


class XAgentApp(App):
    TITLE = "xAgent"
    SUB_TITLE = "TERMINAL AGENT"
    CSS_PATH = "styles.tcss"

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("ctrl+c", "cancel_or_quit", "取消 / 退出", priority=True),
        Binding("escape", "cancel_turn", "中断生成", priority=True),
        Binding("ctrl+l", "clear_conversation", "清空对话"),
        Binding("ctrl+n", "new_conversation", "新会话"),
        Binding("ctrl+b", "toggle_sidebar", "侧栏", priority=True),
        Binding("f1", "show_help", "帮助"),
        Binding("ctrl+q", "quit", "退出"),
    ]

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.agent = Agent(config)
        self._busy = False
        self._cancel_token: CancellationToken | None = None
        self._assistant_bodies: dict[int, Static] = {}
        self._assistant_chunks: dict[int, list[str]] = {}
        self._tool_views: dict[str, tuple[Static, str, float]] = {}
        self._tool_items: dict[str, VerticalGroup] = {}
        self._session_id = secrets.token_hex(4)
        self._turn_count = 0
        self._turn_tool_count = 0
        self._model_calls = 0
        self._turn_started_at: float | None = None
        self._turn_elapsed = 0.0

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #
    def compose(self) -> ComposeResult:
        yield TopBar(id="top-bar")

        with HorizontalGroup(id="body"):
            with VerticalGroup(id="main-pane"):
                with VerticalGroup(id="meta-bar"):
                    with HorizontalGroup(id="meta-ident"):
                        yield Static("xAgent", id="brand", markup=False)
                        yield Static(
                            f"{len(self.agent.tool_names)} 个工具",
                            id="tool-count",
                            markup=False,
                        )
                        yield Static("模型已隐藏", id="model-meta", markup=False)
                    with HorizontalGroup(id="meta-dir"):
                        yield Static("工作目录", id="workdir-label", markup=False)
                        yield Static(str(Path.cwd()), id="workdir", markup=False)
                    yield Static(
                        "Enter 发送   /help 命令   Esc 中断生成   Ctrl+B 侧栏   Ctrl+N 新会话",
                        id="meta-hints",
                        markup=False,
                    )
                with Container(id="chat-frame"):
                    yield ChatLog(id="chat")
                with Container(id="composer"), HorizontalGroup(id="composer-row"):
                    yield Static("›", id="prompt-icon", markup=False)
                    yield Input(
                        placeholder="输入问题后 Enter 发送；/help 查看命令；Esc 中断生成",
                        id="prompt",
                    )
                with VerticalGroup(id="bottom-bar"):
                    with HorizontalGroup(id="status-row"):
                        yield Static("● 就绪", id="status", classes="status-idle", markup=False)
                        yield Static("", id="turn-stats", markup=False)
                        yield Static("Esc 中断", id="esc-hint", markup=False)
                    yield Static(
                        "[#ffa62b]F1[/] 帮助   [#ffa62b]Ctrl+L[/] 清屏   "
                        "[#ffa62b]Ctrl+N[/] 新会话   [#ffa62b]Ctrl+B[/] 侧栏   "
                        "[#ffa62b]Ctrl+Q[/] 退出",
                        id="shortcuts",
                        markup=True,
                    )

            with VerticalScroll(id="sidebar"), VerticalGroup(id="sidebar-inner"):
                yield Static("会话", classes="sidebar-tab active", markup=False)
                with VerticalGroup(id="sidebar-meta"):
                    with HorizontalGroup(classes="side-row"):
                        yield Static("会话", classes="side-label", markup=False)
                        yield Static(
                            self._session_id,
                            id="session-id",
                            classes="side-value",
                            markup=False,
                        )
                    with HorizontalGroup(classes="side-row"):
                        yield Static("模型", classes="side-label", markup=False)
                        yield Static("已隐藏", classes="side-value", markup=False)
                    with HorizontalGroup(classes="side-row"):
                        yield Static("接口", classes="side-label", markup=False)
                        yield Static("已隐藏", classes="side-value", markup=False)
                    with HorizontalGroup(classes="side-row"):
                        yield Static("目录", classes="side-label", markup=False)
                        yield Static(
                            str(Path.cwd()),
                            classes="side-value side-path",
                            markup=False,
                        )
                yield Static("", classes="sidebar-divider", markup=False)
                with HorizontalGroup(id="sidebar-stats"):
                    yield Static(
                        "0 轮",
                        id="sidebar-rounds",
                        classes="side-stat",
                        markup=False,
                    )
                    yield Static(
                        "● 就绪",
                        id="sidebar-status",
                        classes="side-status status-idle",
                        markup=False,
                    )
                yield Static(
                    "模型调用 0 次 · 工具 0 次 · 0.0s",
                    id="sidebar-elapsed",
                    classes="side-sub",
                    markup=False,
                )
                yield Static("", classes="sidebar-divider", markup=False)
                yield Static(
                    f"工具 · {len(self.agent.tool_names)}",
                    id="tools-title",
                    classes="sidebar-title",
                    markup=False,
                )
                for name, description in self.agent.tool_catalog:
                    item = VerticalGroup(
                        Static(f"· {name}", classes="tool-name", markup=False),
                        Static(description, classes="tool-desc", markup=False),
                        classes="tool-item",
                    )
                    self._tool_items[name] = item
                    yield item

    def on_mount(self) -> None:
        self._show_welcome()
        self._set_idle_status()
        self._update_stats()
        if not self.agent.config.llm.has_api_key:
            self._chat.add_message(
                "warning",
                "未配置 api_key，将尝试无鉴权访问（本地 Ollama 等可忽略）",
            )
        self.set_interval(0.5, self._tick_stats)
        self.query_one("#prompt", Input).focus()

    def on_unmount(self) -> None:
        if self._cancel_token is not None:
            self._cancel_token.cancel()

    def _tick_stats(self) -> None:
        if self._busy:
            self._update_stats()

    # ------------------------------------------------------------------ #
    # 输入与命令
    # ------------------------------------------------------------------ #
    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return

        if text.startswith("/"):
            self._handle_command(text)
            return

        if self._busy:
            self._chat.add_message("warning", "上一轮还在处理，请稍候或按 Esc 取消")
            self.bell()
            return

        self._start_turn(text)

    def _handle_command(self, text: str) -> None:
        command = text.lower()
        if command in ("/quit", "/exit"):
            self.action_quit()
        elif command == "/help":
            self._show_help()
        elif command == "/clear":
            self.action_clear_conversation()
        elif command in ("/new", "/new-session"):
            self.action_new_conversation()
        else:
            self._chat.add_message("warning", f"未知命令: {text}，输入 /help 查看帮助")

    def _show_help(self) -> None:
        self._chat.add_message(
            "system",
            "命令:\n"
            "  /help    显示帮助\n"
            "  /clear   清空对话历史\n"
            "  /new     开始新会话\n"
            "  /quit    退出\n"
            "  /exit    退出\n\n"
            "快捷键:\n"
            "  Enter    发送\n"
            "  Esc      中断当前生成\n"
            "  Ctrl+B   显示 / 隐藏侧栏\n"
            "  Ctrl+N   开始新会话\n"
            "  Ctrl+L   清空对话\n"
            "  Ctrl+Q   退出\n\n"
            "已注册工具:\n  " + "\n  ".join(self.agent.tool_names),
        )

    def action_clear_conversation(self) -> None:
        self._clear_conversation("已清空对话历史")

    def action_new_conversation(self) -> None:
        self._clear_conversation("已开始新会话", new_session=True)

    def _clear_conversation(self, message: str, *, new_session: bool = False) -> None:
        if self._busy:
            self._chat.add_message("warning", "正在处理，暂时无法清空")
            return
        try:
            self.agent.clear()
        except AgentBusyError as exc:
            self._chat.add_message("warning", str(exc))
            return

        self._chat.clear_messages()
        self._reset_stats()
        if new_session:
            self._session_id = secrets.token_hex(4)
            self.query_one("#session-id", Static).update(self._session_id)
        self._chat.add_message("system", message)
        self._set_idle_status()
        self._update_stats()
        self.query_one("#prompt", Input).focus()

    def action_cancel_turn(self) -> None:
        if self._busy and self._cancel_token is not None:
            self._cancel_token.cancel()
            self._update_status("正在取消…", "warn")

    def action_cancel_or_quit(self) -> None:
        if self._busy and self._cancel_token is not None:
            self._cancel_token.cancel()
            self._update_status("正在取消…", "warn")
            return
        self.exit()

    def action_toggle_sidebar(self) -> None:
        self.query_one("#body", HorizontalGroup).toggle_class("sidebar-hidden")

    def action_show_help(self) -> None:
        self._show_help()

    def action_quit(self) -> None:
        if self._cancel_token is not None:
            self._cancel_token.cancel()
        self.exit()

    # ------------------------------------------------------------------ #
    # 回合执行
    # ------------------------------------------------------------------ #
    def _start_turn(self, text: str) -> None:
        self._busy = True
        self._cancel_token = CancellationToken()
        self._reset_round_state()
        self._turn_count += 1
        self._turn_tool_count = 0
        self._model_calls = 0
        self._turn_started_at = perf_counter()
        self._turn_elapsed = 0.0
        self._chat.add_message("user", text)
        self._set_busy_status("请求中…")
        self._update_stats()

        prompt = self.query_one("#prompt", Input)
        prompt.disabled = True
        self._run_agent(text, self._cancel_token)

    @work(thread=True, exclusive=True, group="agent")
    def _run_agent(self, text: str, token: CancellationToken) -> None:
        def on_event(event) -> None:
            # 应用正在退出时 UI 线程可能已不可用，忽略即可
            with suppress(Exception):
                self.call_from_thread(self._handle_event, event)

        try:
            self.agent.send(text, on_event=on_event, cancel=token)
        except Exception as exc:  # noqa: BLE001 - worker 兜底，需把界面恢复为可输入
            with suppress(Exception):
                self.call_from_thread(self._finish_with_error, str(exc))

    def _handle_event(self, event) -> None:
        if isinstance(event, TurnStarted):
            self._update_status("请求中…")
        elif isinstance(event, AssistantDelta):
            self._handle_assistant_delta(event)
        elif isinstance(event, AssistantCompleted):
            self._handle_assistant_completed(event)
        elif isinstance(event, ToolCallStarted):
            self._handle_tool_started(event)
        elif isinstance(event, ToolCallFinished):
            self._handle_tool_finished(event)
        elif isinstance(event, TurnFinished):
            self._finish_turn(event)

    def _handle_assistant_delta(self, event: AssistantDelta) -> None:
        chunks = self._assistant_chunks.setdefault(event.round_index, [])
        chunks.append(event.text)

        body = self._assistant_bodies.get(event.round_index)
        if body is None:
            body = self._chat.add_message("assistant", "")
            self._assistant_bodies[event.round_index] = body
        self._chat.update_message(body, "".join(chunks))

    def _handle_assistant_completed(self, event: AssistantCompleted) -> None:
        self._model_calls = max(self._model_calls, event.round_index + 1)
        body = self._assistant_bodies.get(event.round_index)
        if event.content and body is None:
            self._chat.add_message("assistant", event.content)
        self._update_stats()

    def _handle_tool_started(self, event: ToolCallStarted) -> None:
        key = event.tool_call_id or f"{event.round_index}:{event.name}"
        header = self._tool_header(event.name, event.arguments)
        body = self._chat.add_message(
            "tool",
            self._tool_body(event.arguments, None),
            title=header,
        )
        self._tool_views[key] = (body, event.arguments, perf_counter())
        self._mark_tool(event.name, "tool-active")
        self._update_status(f"运行 {event.name}…", "busy")
        self._update_stats()

    def _handle_tool_finished(self, event: ToolCallFinished) -> None:
        key = event.tool_call_id or f"{event.round_index}:{event.name}"
        view = self._tool_views.pop(key, None)
        if view is not None:
            body, arguments, started_at = view
            duration = self._format_duration((perf_counter() - started_at) * 1000)
            header = self._tool_header(event.name, arguments, duration)
            body.add_class("tool-error" if event.is_error else "tool-ok")
            self._chat.update_message(
                body,
                self._tool_body(arguments, event.output, event.is_error),
                role_text=header,
            )
        self._turn_tool_count += 1
        self._mark_tool(event.name, "tool-error" if event.is_error else "tool-done")
        self._update_status("请求中…")
        self._update_stats()

    def _finish_turn(self, event: TurnFinished) -> None:
        self._busy = False
        self._cancel_token = None
        if self._turn_started_at is not None:
            self._turn_elapsed = perf_counter() - self._turn_started_at
        self._turn_started_at = None
        self._reset_round_state()

        if event.cancelled:
            self._chat.add_message("system", "本轮已取消")
        elif not event.ok and event.error:
            self._chat.add_message("error", event.error)

        prompt = self.query_one("#prompt", Input)
        prompt.disabled = False
        prompt.focus()
        self._set_idle_status()
        self._update_stats()

    def _finish_with_error(self, message: str) -> None:
        if not self._busy:
            return
        self._busy = False
        self._cancel_token = None
        if self._turn_started_at is not None:
            self._turn_elapsed = perf_counter() - self._turn_started_at
        self._turn_started_at = None
        self._reset_round_state()
        self._chat.add_message("error", f"执行失败: {message}")

        prompt = self.query_one("#prompt", Input)
        prompt.disabled = False
        prompt.focus()
        self._set_idle_status()
        self._update_stats()

    # ------------------------------------------------------------------ #
    # 状态与辅助
    # ------------------------------------------------------------------ #
    @property
    def _chat(self) -> ChatLog:
        return self.query_one("#chat", ChatLog)

    def _reset_round_state(self) -> None:
        self._assistant_bodies.clear()
        self._assistant_chunks.clear()
        self._tool_views.clear()

    def _reset_stats(self) -> None:
        self._turn_count = 0
        self._turn_tool_count = 0
        self._model_calls = 0
        self._turn_started_at = None
        self._turn_elapsed = 0.0

    def _show_welcome(self) -> None:
        self._chat.add_message(
            "system",
            "xAgent 已就绪 · 输入问题开始对话，/help 查看命令。",
        )

    def _set_idle_status(self) -> None:
        self._update_status("就绪", "idle")

    def _set_busy_status(self, state: str) -> None:
        self._update_status(state, "busy")

    def _update_status(self, state: str, tone: str = "idle") -> None:
        status = self.query_one("#status", Static)
        status.update(f"● {state}")
        status.set_classes(f"status-{tone}")
        sidebar_status = self.query_one("#sidebar-status", Static)
        sidebar_status.update(f"● {state}")
        sidebar_status.set_classes(f"side-status status-{tone}")

    def _update_stats(self) -> None:
        elapsed = self._format_elapsed()
        self.query_one("#turn-stats", Static).update(
            f"{self._turn_count} 轮 · 工具 {self._turn_tool_count} 次 · {elapsed}"
        )
        self.query_one("#sidebar-rounds", Static).update(f"{self._turn_count} 轮")
        self.query_one("#sidebar-elapsed", Static).update(
            f"模型调用 {self._model_calls} 次 · 工具 {self._turn_tool_count} 次 · {elapsed}"
        )

    def _format_elapsed(self) -> str:
        if self._turn_started_at is not None:
            elapsed = perf_counter() - self._turn_started_at
        else:
            elapsed = self._turn_elapsed
        return f"{elapsed:.1f}s"

    def _mark_tool(self, name: str, state: str) -> None:
        item = self._tool_items.get(name)
        if item is None:
            return
        for css_class in ("tool-active", "tool-done", "tool-error"):
            item.remove_class(css_class)
        item.add_class(state)

    @staticmethod
    def _format_arguments(raw: str) -> str:
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return raw.strip()
        if not isinstance(data, dict):
            return json.dumps(data, ensure_ascii=False)
        parts = []
        for key, value in data.items():
            if isinstance(value, str):
                parts.append(f"{key}={value}")
            else:
                parts.append(f"{key}={json.dumps(value, ensure_ascii=False)}")
        return ", ".join(parts)

    @classmethod
    def _tool_header(cls, name: str, arguments: str, duration: str = "") -> str:
        args = cls._format_arguments(arguments)
        suffix = f" · {duration}" if duration else ""
        return f"调用工具: {name}({args}){suffix}"

    @classmethod
    def _tool_body(cls, arguments: str, output: str | None, is_error: bool = False) -> str:
        args = cls._format_arguments(arguments) or "{}"
        lines = ["参数", args, "", "结果"]
        if output is None:
            lines.append("执行中…")
        elif is_error:
            lines.append(f"执行失败: {output}")
        else:
            lines.append(output.strip() or "(无输出)")
        return "\n".join(lines)

    @staticmethod
    def _format_duration(milliseconds: float) -> str:
        if milliseconds < 1000:
            return f"{milliseconds:.0f} ms"
        return f"{milliseconds / 1000:.1f} s"


def main() -> None:
    try:
        config = AppConfig.load()
    except Exception as exc:
        print(f"配置加载失败: {exc}")
        raise SystemExit(1) from exc

    XAgentApp(config).run()
