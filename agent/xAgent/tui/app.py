# -*- coding: utf-8 -*-
"""Textual 适配层。

该文件是 core 与具体 UI 的唯一耦合点：
- 把 Agent 事件映射为控件更新
- 把键盘 / 输入框操作映射为 Agent 调用
新增 Web / Desktop 界面时，不需要改动 core，只需新增类似的适配层。
"""
from __future__ import annotations

import json
from contextlib import suppress
from time import perf_counter
from typing import ClassVar

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, HorizontalGroup, VerticalGroup, VerticalScroll
from textual.widgets import Static

from core import (
    Agent,
    AgentBusyError,
    AppConfig,
    AssistantCompleted,
    AssistantDelta,
    CancellationToken,
    CompactionFinished,
    CompactionStarted,
    ContextStatus,
    ContextUsageUpdated,
    ToolCallFinished,
    ToolCallStarted,
    TurnFinished,
    TurnStarted,
)
from core.config import ensure_config_file

from .widgets import (
    ChatLog,
    CompactionScreen,
    ConfigCreatedScreen,
    PromptArea,
    SessionPickerScreen,
    SlashMenu,
    TopBar,
    WelcomeCard,
)

SLASH_COMMANDS: list[tuple[str, str]] = [
    ("/help", "显示帮助"),
    ("/new", "保存当前会话并新建会话"),
    ("/save", "保存当前会话"),
    ("/resume", "选择并恢复已保存会话"),
    ("/sessions", "同 /resume"),
    ("/compact", "压缩当前上下文并归档"),
    ("/clear", "清空当前对话"),
    ("/tools", "列出已注册工具"),
    ("/skills", "列出 Agent Skills"),
    ("/status", "显示会话与上下文状态"),
    ("/exit", "保存并退出"),
    ("/quit", "保存并退出"),
]


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

    def __init__(self, config: AppConfig, config_created=None) -> None:
        super().__init__()
        self.agent = Agent(config)
        self._busy = False
        self._cancel_token: CancellationToken | None = None
        self._assistant_bodies: dict[int, Static] = {}
        self._assistant_chunks: dict[int, list[str]] = {}
        self._tool_views: dict[str, tuple[Static, str, float]] = {}
        self._tool_items: dict[str, VerticalGroup] = {}
        self._config_created = config_created
        self._slash_options: list[tuple[str, str]] = []
        self._reported_mcp_issues: set[str] = set()
        self._turn_count = 0
        self._turn_tool_count = 0
        self._model_calls = 0
        self._turn_started_at: float | None = None
        self._turn_elapsed = 0.0
        self._context_warned = False

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #
    def compose(self) -> ComposeResult:
        yield TopBar(id="top-bar")

        with HorizontalGroup(id="body"):
            with VerticalGroup(id="main-pane"):
                with Container(id="chat-frame"):
                    yield ChatLog(id="chat")
                with Container(id="composer"):
                    yield SlashMenu()
                    with HorizontalGroup(id="composer-row"):
                        yield Static("›", id="prompt-icon", markup=False)
                        yield PromptArea(
                            placeholder=(
                                "输入问题后 Enter 发送；Shift+Enter 换行；"
                                "/help 查看命令；Esc 中断生成"
                            ),
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
                            self.agent.session_id,
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
                        yield Static("项目", classes="side-label", markup=False)
                        yield Static(
                            str(self.agent.project_root),
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
                    "MCP · 加载中",
                    id="mcp-title",
                    classes="sidebar-title",
                    markup=False,
                )
                with VerticalGroup(id="mcp-list"):
                    yield Static(
                        "正在读取 .mcp.json…",
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
                with VerticalGroup(id="tools-list"):
                    pass

    def on_mount(self) -> None:
        prompt = self.query_one("#prompt", PromptArea)
        prompt.slash_controller = self._handle_slash_key

        if self._config_created is not None:
            self.push_screen(
                ConfigCreatedScreen(self._config_created),
                callback=lambda _result: self.exit(),
            )
            return

        self._show_welcome()
        self._render_tools()
        self._render_mcp()
        self._report_mcp_issues(self.agent.mcp_issues)
        self._set_idle_status()
        self._update_stats()
        self._update_context_display(self.agent.context_status)
        if not self.agent.config.llm.has_api_key:
            self._chat.add_message(
                "warning",
                "未配置 api_key，将尝试无鉴权访问（本地 Ollama 等可忽略）",
            )
        self.set_interval(0.5, self._tick_stats)
        self._start_mcp_loading()
        prompt.focus()

    def on_unmount(self) -> None:
        if self._cancel_token is not None:
            self._cancel_token.cancel()
        if self.agent.has_session_content:
            with suppress(Exception):
                self.agent.save_session()
        self.agent.close()

    def _tick_stats(self) -> None:
        if self._busy:
            self._update_stats()

    def _start_mcp_loading(self) -> None:
        self._render_mcp()
        if not self.agent.mcp_servers:
            return
        self.query_one("#tools-title", Static).update(
            f"工具 · {len(self.agent.tool_names)}（MCP 连接中…）"
        )
        self._connect_mcp_worker()

    @work(thread=True, group="mcp", exclusive=True)
    def _connect_mcp_worker(self) -> None:
        try:
            issues = self.agent.connect_mcp()
        except Exception as exc:  # noqa: BLE001 - 后台连接失败不能影响界面
            issues = [f"MCP 连接失败: {exc}"]
        with suppress(Exception):
            self.call_from_thread(self._finish_mcp_loading, issues)

    def _finish_mcp_loading(self, issues) -> None:
        self._render_mcp()
        self._render_tools()
        for card in self.query(WelcomeCard):
            card.set_tool_count(len(self.agent.tool_names))
        self._report_mcp_issues(issues)
        self._update_context_display(self.agent.context_status)
        self._update_stats()

    def _report_mcp_issues(self, issues) -> None:
        for issue in issues:
            if issue in self._reported_mcp_issues:
                continue
            self._reported_mcp_issues.add(issue)
            self._chat.add_message("error", issue)

    def _render_mcp(self) -> None:
        title = self.query_one("#mcp-title", Static)
        container = self.query_one("#mcp-list", VerticalGroup)
        container.remove_children()
        statuses = self.agent.mcp_statuses
        if not statuses:
            title.update("MCP · 未配置")
            container.mount(
                Static(
                    "未发现 .mcp.json",
                    classes="side-sub",
                    markup=False,
                )
            )
            return

        connected = sum(1 for item in statuses if item.state == "connected")
        title.update(f"MCP · {connected}/{len(statuses)} 已连接")
        labels = {
            "pending": "等待",
            "connecting": "连接中…",
            "connected": "已连接",
            "error": "失败",
        }
        for item in statuses:
            state_text = labels.get(item.state, item.state)
            if item.state == "connected":
                state_text = f"{state_text} · {item.tool_count} 工具"
            row = VerticalGroup(
                Static(f"· {item.name}", classes="mcp-name", markup=False),
                Static(state_text, classes="mcp-state", markup=False),
                classes=f"mcp-item mcp-{item.state}",
            )
            container.mount(row)

    def _render_tools(self) -> None:
        container = self.query_one("#tools-list", VerticalGroup)
        container.remove_children()
        self._tool_items.clear()
        for name, description in self.agent.tool_catalog:
            item = VerticalGroup(
                Static(f"· {name}", classes="tool-name", markup=False),
                Static(description, classes="tool-desc", markup=False),
                classes="tool-item",
            )
            self._tool_items[name] = item
            container.mount(item)
        self.query_one("#tools-title", Static).update(
            f"工具 · {len(self.agent.tool_names)}"
        )

    # ------------------------------------------------------------------ #
    # 输入与命令
    # ------------------------------------------------------------------ #
    def on_text_area_changed(self, event) -> None:
        if getattr(event.text_area, "id", "") == "prompt":
            self._refresh_slash_menu(event.text_area.text)

    def on_prompt_area_submitted(self, event: PromptArea.Submitted) -> None:
        text = event.value.strip()
        event.prompt.text = ""
        self._hide_slash_menu()
        if not text:
            return

        if text.startswith("/"):
            self._handle_command(text)
            return

        if self._busy:
            self._chat.add_message("warning", "上一轮还在处理，请稍候或按 Esc 取消")
            self.bell()
            return

        if self.agent.needs_compaction:
            status = self.agent.context_status
            self._chat.add_message(
                "warning",
                f"上下文已使用 {status.ratio:.0%}，请先执行 /compact 压缩上下文后再继续输入。",
            )
            self.bell()
            return

        self._start_turn(text)

    def _handle_command(self, text: str) -> None:
        command = text.split(maxsplit=1)[0].lower()
        if command in ("/quit", "/exit"):
            self.action_quit()
        elif command == "/help":
            self._show_help()
        elif command == "/clear":
            self.action_clear_conversation()
        elif command in ("/new", "/new-session"):
            self.action_new_conversation()
        elif command == "/save":
            self._save_current_session()
        elif command in ("/resume", "/sessions"):
            self._open_resume()
        elif command == "/compact":
            self._start_compaction()
        elif command == "/tools":
            self._show_tools()
        elif command == "/skills":
            self._show_skills()
        elif command == "/status":
            self._show_status()
        else:
            self._chat.add_message("warning", f"未知命令: {text}，输入 /help 查看帮助")

    def _show_help(self) -> None:
        command_lines = "\n".join(
            f"  {name:<10} {description}" for name, description in SLASH_COMMANDS
        )
        self._chat.add_message(
            "system",
            "命令:\n"
            f"{command_lines}\n\n"
            "快捷键:\n"
            "  Enter          发送\n"
            "  Shift+Enter    换行（Ctrl+J 同效）\n"
            "  Esc            中断当前生成 / 关闭补全\n"
            "  Ctrl+B         显示 / 隐藏侧栏\n"
            "  Ctrl+N         保存并开始新会话\n"
            "  Ctrl+L         清空对话\n"
            "  Ctrl+Q         保存并退出\n\n"
            "已注册工具:\n  " + "\n  ".join(self.agent.tool_names),
        )

    def _show_tools(self) -> None:
        lines = [f"- {name}: {description}" for name, description in self.agent.tool_catalog]
        self._chat.add_message(
            "system",
            f"已注册工具（{len(lines)}）:\n" + ("\n".join(lines) or "(无)"),
        )

    def _show_skills(self) -> None:
        skills = self.agent.skills.skills
        if not skills:
            self._chat.add_message("system", "当前项目未发现 Agent Skills。")
            return
        lines = [f"- {skill.name}: {skill.description}" for skill in skills]
        self._chat.add_message(
            "system",
            f"Agent Skills（{len(lines)}）:\n" + "\n".join(lines),
        )

    def _show_status(self) -> None:
        status = self.agent.context_status
        mcp_lines = [
            f"- {item.name}: {item.state} · {item.tool_count} 个工具"
            + (f" · {item.error}" if item.error else "")
            for item in self.agent.mcp_statuses
        ] or ["- 未配置 MCP Server"]
        self._chat.add_message(
            "system",
            f"会话: {self.agent.session_id}\n"
            f"标题: {self.agent.session_title}\n"
            f"保存路径: {self.agent.session_path}\n"
            f"轮次: {self.agent.session_turn_count}\n"
            f"上下文: {status.used_tokens:,} / {status.window_tokens:,} tokens"
            f" ({status.ratio:.0%})\n\n"
            "MCP:\n" + "\n".join(mcp_lines),
        )

    def action_clear_conversation(self) -> None:
        self._clear_conversation("已清空对话历史")

    def action_new_conversation(self) -> None:
        self._start_new_session()

    def _clear_conversation(self, message: str) -> None:
        if self._busy:
            self._chat.add_message("warning", "正在处理，暂时无法清空")
            return
        try:
            self.agent.clear()
        except AgentBusyError as exc:
            self._chat.add_message("warning", str(exc))
            return

        self._chat.clear_messages()
        self._show_welcome()
        self._reset_stats()
        self._chat.add_message("system", message)
        self._set_idle_status()
        self._update_stats()
        self._context_warned = False
        self._update_context_display(self.agent.context_status)
        self.query_one("#prompt", PromptArea).focus()

    def _start_new_session(self) -> None:
        if self._busy:
            self._chat.add_message("warning", "正在处理，暂时无法新建会话")
            return
        old_id = self.agent.session_id
        had_content = self.agent.has_session_content
        try:
            new_id = self.agent.start_new_session(save_current=True)
        except (AgentBusyError, OSError, ValueError) as exc:
            self._chat.add_message("error", f"新建会话失败: {exc}")
            return

        self._chat.clear_messages()
        self._show_welcome()
        self._reset_stats()
        self.query_one("#session-id", Static).update(new_id)
        if had_content:
            self._chat.add_message(
                "system",
                f"已保存会话 {old_id}，开始新会话 {new_id}。",
            )
        else:
            self._chat.add_message("system", f"已开始新会话 {new_id}。")
        self._set_idle_status()
        self._update_stats()
        self._context_warned = False
        self._update_context_display(self.agent.context_status)
        self.query_one("#prompt", PromptArea).focus()

    def _save_current_session(self) -> None:
        try:
            path = self.agent.save_session()
        except (OSError, ValueError) as exc:
            self._chat.add_message("error", f"保存会话失败: {exc}")
            return
        self._chat.add_message("system", f"会话已保存: {path}")

    def _open_resume(self) -> None:
        if self._busy:
            self._chat.add_message("warning", "正在处理，暂时无法恢复会话")
            return
        sessions = self.agent.list_sessions()
        self.push_screen(
            SessionPickerScreen(sessions),
            callback=self._resume_selected,
        )

    def _resume_selected(self, session_id) -> None:
        if not session_id:
            return
        try:
            title = self.agent.load_session(session_id)
        except (OSError, ValueError, AgentBusyError) as exc:
            self._chat.add_message("error", f"恢复会话失败: {exc}")
            return

        self._chat.clear_messages()
        self._show_welcome()
        self._render_history(self.agent.history)
        self._reset_stats()
        self._turn_count = self.agent.session_turn_count
        self.query_one("#session-id", Static).update(self.agent.session_id)
        self._chat.add_message("system", f"已恢复会话: {title}")
        self._set_idle_status()
        self._update_stats()
        self._context_warned = False
        self._update_context_display(self.agent.context_status)
        self.query_one("#prompt", PromptArea).focus()

    def _render_history(self, messages) -> None:
        for index, message in enumerate(messages):
            if index == 0:
                continue
            role = message.get("role")
            content = message.get("content")
            if role == "system":
                continue
            if role == "assistant":
                if isinstance(content, str) and content.strip():
                    self._chat.add_message("assistant", content)
                tool_calls = message.get("tool_calls")
                if isinstance(tool_calls, list) and tool_calls:
                    names = []
                    for call in tool_calls:
                        fn = call.get("function") if isinstance(call, dict) else None
                        if isinstance(fn, dict) and fn.get("name"):
                            names.append(str(fn["name"]))
                    if names:
                        self._chat.add_message(
                            "tool",
                            "调用工具: " + ", ".join(names),
                            title="工具调用",
                        )
            elif role == "tool":
                if isinstance(content, str):
                    self._chat.add_message(
                        "tool",
                        self._truncate_history_text(content),
                        title="工具结果",
                    )
            elif role == "user" and isinstance(content, str):
                self._chat.add_message("user", content)

    @staticmethod
    def _truncate_history_text(text: str, limit: int = 4000) -> str:
        if len(text) <= limit:
            return text
        return text[:limit].rstrip() + "\n\n... [历史内容过长，已截断]"

    def action_cancel_turn(self) -> None:
        if self._hide_slash_menu():
            return
        if self._busy and self._cancel_token is not None:
            self._cancel_token.cancel()
            self._update_status("正在取消…", "warn")

    def action_cancel_or_quit(self) -> None:
        if self._busy and self._cancel_token is not None:
            self._cancel_token.cancel()
            self._update_status("正在取消…", "warn")
            return
        self.action_quit()

    def action_toggle_sidebar(self) -> None:
        self.query_one("#body", HorizontalGroup).toggle_class("sidebar-hidden")

    def action_show_help(self) -> None:
        self._show_help()

    def action_quit(self) -> None:
        if self._cancel_token is not None:
            self._cancel_token.cancel()
        self._save_before_exit()
        self.exit()

    def _save_before_exit(self) -> None:
        if self.agent.has_session_content:
            with suppress(Exception):
                self.agent.save_session()

    def _refresh_slash_menu(self, text: str) -> None:
        menu = self.query_one("#slash-menu", SlashMenu)
        if self._busy or self._config_created is not None:
            self._hide_slash_menu()
            return
        if not text.startswith("/") or any(char.isspace() for char in text):
            self._hide_slash_menu()
            return

        prefix = text.lower()
        options = [
            (name, description)
            for name, description in SLASH_COMMANDS
            if name.startswith(prefix)
        ]
        if not options:
            self._hide_slash_menu()
            return
        self._slash_options = options
        menu.set_options(options, 0)

    def _hide_slash_menu(self) -> bool:
        menu = self.query_one("#slash-menu", SlashMenu)
        was_visible = menu.has_class("visible")
        menu.hide()
        self._slash_options = []
        return was_visible

    def _handle_slash_key(self, key: str) -> bool:
        menu = self.query_one("#slash-menu", SlashMenu)
        if not menu.has_options:
            return False
        if key in {"up", "down"}:
            menu.move(-1 if key == "up" else 1)
            return True
        if key in {"enter", "tab"}:
            command = menu.current_command()
            prompt = self.query_one("#prompt", PromptArea)
            if command:
                prompt.text = f"{command} "
                prompt.cursor_location = (0, len(command) + 1)
            self._hide_slash_menu()
            prompt.focus()
            return True
        if key == "escape":
            self._hide_slash_menu()
            return True
        return False

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

        prompt = self.query_one("#prompt", PromptArea)
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

    def _start_compaction(self) -> None:
        if self._busy:
            self._chat.add_message("warning", "当前有任务正在执行，请稍候或按 Esc 取消")
            self.bell()
            return

        self._busy = True
        self._cancel_token = CancellationToken()
        self._reset_round_state()
        self._chat.add_message("system", "正在压缩上下文，请稍候…")
        self._set_busy_status("压缩上下文…")
        self._update_stats()

        prompt = self.query_one("#prompt", PromptArea)
        prompt.disabled = True
        self._run_compaction(self._cancel_token)

    @work(thread=True, exclusive=True, group="agent")
    def _run_compaction(self, token: CancellationToken) -> None:
        def on_event(event) -> None:
            with suppress(Exception):
                self.call_from_thread(self._handle_event, event)

        try:
            self.agent.compact(on_event=on_event, cancel=token)
        except Exception as exc:  # noqa: BLE001 - worker 兜底，需恢复输入
            with suppress(Exception):
                self.call_from_thread(self._finish_with_error, str(exc))

    def _finish_compaction(self, event: CompactionFinished) -> None:
        self._busy = False
        self._cancel_token = None
        self._reset_round_state()

        prompt = self.query_one("#prompt", PromptArea)
        prompt.disabled = False

        if event.ok:
            self._context_warned = False
            self._chat.add_message(
                "system",
                f"上下文压缩完成，原始上下文已归档为 {event.archive_id}。",
            )
            self.push_screen(
                CompactionScreen(
                    event.original_text,
                    event.summary,
                    event.archive_id,
                    event.timestamp,
                )
            )
        elif event.error:
            self._chat.add_message("error", f"上下文压缩失败：{event.error}")

        self._set_idle_status()
        self._update_stats()
        self._update_context_display(self.agent.context_status)
        prompt.focus()

    def _handle_context_usage(self, event: ContextUsageUpdated) -> None:
        self._update_context_display_event(event)
        if event.warning and not self._context_warned:
            self._context_warned = True
            self._chat.add_message(
                "warning",
                f"上下文已使用 {event.ratio:.0%}"
                f"（{event.used_tokens:,} / {event.window_tokens:,} tokens）。"
                "请执行 /compact 压缩上下文，否则将暂停接受新的普通提示词。",
            )
            self.bell()
        elif not event.warning:
            self._context_warned = False

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
        elif isinstance(event, ContextUsageUpdated):
            self._handle_context_usage(event)
        elif isinstance(event, CompactionStarted):
            self._update_status("压缩上下文…", "busy")
        elif isinstance(event, CompactionFinished):
            self._finish_compaction(event)
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

        prompt = self.query_one("#prompt", PromptArea)
        prompt.disabled = False
        prompt.focus()
        self._set_idle_status()
        self._update_stats()
        self._update_context_display(self.agent.context_status)

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

        prompt = self.query_one("#prompt", PromptArea)
        prompt.disabled = False
        prompt.focus()
        self._set_idle_status()
        self._update_stats()
        self._update_context_display(self.agent.context_status)

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
        self._chat.add_welcome(
            str(self.agent.project_root),
            len(self.agent.tool_names),
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

    def _update_context_display(self, status: ContextStatus) -> None:
        default_text = "（默认）" if status.default_window else ""
        text = (
            f"上下文 {status.used_tokens / 1000:.1f}k / "
            f"{status.window_tokens / 1000:.0f}k{default_text} · {status.ratio:.0%}"
        )
        label = self.query_one("#top-context", Static)
        label.update(text)
        label.set_classes("context-warn" if status.warning else "context-ok")

    def _update_context_display_event(self, event: ContextUsageUpdated) -> None:
        default_text = "（默认）" if event.default_window else ""
        text = (
            f"上下文 {event.used_tokens / 1000:.1f}k / "
            f"{event.window_tokens / 1000:.0f}k{default_text} · {event.ratio:.0%}"
        )
        label = self.query_one("#top-context", Static)
        label.update(text)
        label.set_classes("context-warn" if event.warning else "context-ok")

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
        config_path, created = ensure_config_file()
        config = AppConfig.load(config_path)
    except Exception as exc:
        print(f"配置加载失败: {exc}")
        raise SystemExit(1) from exc

    XAgentApp(
        config,
        config_created=config_path if created else None,
    ).run()
