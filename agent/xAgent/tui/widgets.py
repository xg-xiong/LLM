# -*- coding: utf-8 -*-
"""TUI 专用控件。

这里只负责“怎么显示”，不包含任何 LLM / 工具业务逻辑。
"""
from __future__ import annotations

from contextlib import suppress
from datetime import datetime

from textual import events
from textual.containers import HorizontalGroup, VerticalGroup, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, OptionList, Static, TextArea
from textual.widgets.option_list import Option

ROLE_LABELS = {
    "user": "",
    "assistant": "xAgent",
    "tool": "工具",
    "error": "错误",
    "system": "",
    "warning": "提示",
}

class TopBar(HorizontalGroup):
    """顶部标题栏：品牌与实时时钟。"""

    def compose(self):
        yield Static("xAgent  ·  TERMINAL AGENT", id="top-title", markup=False)
        yield Static("", id="top-context", markup=False, classes="context-ok")
        yield Static("", id="top-clock", markup=False)

    def on_mount(self) -> None:
        self._update_clock()
        self.set_interval(1, self._update_clock)

    def _update_clock(self) -> None:
        self.query_one("#top-clock", Static).update(datetime.now().strftime("%H:%M:%S"))


class SlashMenu(Static):
    """输入框上方的斜杠命令补全面板。"""

    def __init__(self) -> None:
        super().__init__("", id="slash-menu", markup=False)
        self._options: list[tuple[str, str]] = []
        self.selected = 0

    @property
    def has_options(self) -> bool:
        return bool(self._options) and self.has_class("visible")

    def set_options(
        self,
        options: list[tuple[str, str]],
        selected: int = 0,
    ) -> None:
        self._options = options
        self.selected = max(0, min(selected, len(options) - 1)) if options else 0
        self._render_menu()
        if options:
            self.add_class("visible")
        else:
            self.remove_class("visible")

    def hide(self) -> None:
        self.remove_class("visible")

    def move(self, delta: int) -> None:
        if not self._options:
            return
        self.selected = (self.selected + delta) % len(self._options)
        self._render_menu()

    def current_command(self) -> str | None:
        if not self._options:
            return None
        return self._options[self.selected][0]

    def _render_menu(self) -> None:
        lines = []
        for index, (command, description) in enumerate(self._options):
            marker = "›" if index == self.selected else " "
            lines.append(f"{marker} {command:<12} {description}")
        self.update("\n".join(lines))


class WelcomeCard(VerticalGroup):
    """启动时的欢迎卡片，样式接近 Claude Code 的终端欢迎框。"""

    def __init__(self, project_root: str, tool_count: int) -> None:
        super().__init__(classes="welcome-card")
        self.border_title = "Welcome back"
        self._project_root = project_root
        self._tool_count = tool_count
        self._tool_value: Static | None = None

    def compose(self):
        yield Static(
            "✻  xAgent  ·  TERMINAL AGENT",
            classes="welcome-brand",
            markup=False,
        )
        yield Static(
            "输入问题开始对话，Enter 发送；/help 查看命令。",
            classes="welcome-copy",
            markup=False,
        )
        yield Static("", classes="welcome-gap", markup=False)
        with HorizontalGroup(classes="welcome-meta-row"):
            yield Static("项目", classes="welcome-label", markup=False)
            yield Static(
                self._project_root,
                classes="welcome-value",
                markup=False,
            )
        with HorizontalGroup(classes="welcome-meta-row"):
            yield Static("工具", classes="welcome-label", markup=False)
            self._tool_value = Static(
                self._tool_text(),
                classes="welcome-value",
                markup=False,
            )
            yield self._tool_value
        yield Static("", classes="welcome-gap", markup=False)
        yield Static(
            "Tips  /new 新会话   /clear 清空   Ctrl+B 侧栏",
            classes="welcome-tip",
            markup=False,
        )

    def _tool_text(self) -> str:
        return f"{self._tool_count} 个 · 模型已隐藏"

    def set_tool_count(self, tool_count: int) -> None:
        self._tool_count = tool_count
        if self._tool_value is not None:
            self._tool_value.update(self._tool_text())


class SessionPickerScreen(ModalScreen):
    """恢复会话浮层：上下选择，Enter 恢复，Esc 取消。"""

    BINDINGS = [("escape", "close_panel", "取消")]

    def __init__(self, sessions) -> None:
        super().__init__()
        self._sessions = list(sessions)

    def compose(self):
        with VerticalGroup(id="resume-dialog"):
            yield Static(
                "恢复会话",
                id="resume-title",
                markup=False,
            )
            yield Static(
                "选择要恢复的会话。当前会话会先自动保存。",
                classes="resume-hint",
                markup=False,
            )
            if self._sessions:
                options = []
                for session in self._sessions:
                    updated = session.updated_at or "未知时间"
                    prompt = (
                        f"{session.title}  ·  {updated}  ·  "
                        f"{session.turn_count} 轮  ·  {session.id}"
                    )
                    options.append(Option(prompt, id=session.id))
                yield OptionList(
                    *options,
                    id="session-list",
                    markup=False,
                )
            else:
                yield Static(
                    "暂无已保存的会话。",
                    id="session-empty",
                    markup=False,
                )
            with HorizontalGroup(id="resume-actions"):
                yield Static(
                    "↑/↓ 选择 · Enter 恢复 · Esc 取消",
                    classes="resume-hint",
                    markup=False,
                )
                yield Button("取消", id="resume-cancel")

    def on_mount(self) -> None:
        if self._sessions:
            self.query_one("#session-list", OptionList).focus()
        else:
            self.query_one("#resume-cancel", Button).focus()

    def on_option_list_option_selected(
        self,
        event: OptionList.OptionSelected,
    ) -> None:
        event.stop()
        self.dismiss(event.option.id)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(None)

    def action_close_panel(self) -> None:
        self.dismiss(None)


class ConfigCreatedScreen(ModalScreen):
    """首次运行生成 config.ini 后的提示浮层。"""

    BINDINGS = [("escape", "close_panel", "退出")]

    def __init__(self, path) -> None:
        super().__init__()
        self._path = path

    def compose(self):
        with VerticalGroup(id="config-created-dialog"):
            yield Static(
                "已生成默认配置文件",
                id="config-created-title",
                markup=False,
            )
            yield Static(
                f"首次运行未找到 config.ini，已在以下位置生成完整模板：\n\n"
                f"{self._path}\n\n"
                "请编辑 base_url、model_name、api_key 等配置后重新启动 xAgent。",
                id="config-created-text",
                markup=False,
            )
            yield Button("退出", id="config-created-close", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#config-created-close", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(True)

    def action_close_panel(self) -> None:
        self.dismiss(True)


class CompactionScreen(ModalScreen):
    """压缩结果浮层：左侧原文，右侧摘要，可分别滚动。"""

    BINDINGS = [("escape", "close_panel", "关闭")]

    def __init__(
        self,
        original_text: str,
        summary: str,
        archive_id: str,
        timestamp: str,
    ) -> None:
        super().__init__()
        self._original_text = original_text
        self._summary = summary
        self._archive_id = archive_id
        self._timestamp = timestamp

    def compose(self):
        with VerticalGroup(id="compact-dialog"):
            yield Static(
                f"上下文压缩 · 归档 {self._archive_id} · {self._timestamp}",
                id="compact-title",
                markup=False,
            )
            with HorizontalGroup(id="compact-columns"):
                with VerticalGroup(classes="compact-column"):
                    yield Static("压缩前原文", classes="compact-heading", markup=False)
                    with VerticalScroll(classes="compact-scroll"):
                        yield Static(
                            self._original_text or "(空)",
                            classes="compact-text",
                            markup=False,
                        )
                with VerticalGroup(classes="compact-column"):
                    yield Static("压缩后摘要", classes="compact-heading", markup=False)
                    with VerticalScroll(classes="compact-scroll"):
                        yield Static(
                            self._summary or "(空)",
                            classes="compact-text",
                            markup=False,
                        )
            yield Button("关闭", id="compact-close", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss()

    def action_close_panel(self) -> None:
        self.dismiss()


class PromptArea(TextArea):
    """多行输入框：Enter 发送，Shift+Enter / Ctrl+J 换行。"""

    class Submitted(Message):
        def __init__(self, prompt: PromptArea, value: str) -> None:
            super().__init__()
            self.prompt = prompt
            self.value = value

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.slash_controller = None

    async def _on_key(self, event: events.Key) -> None:
        if (
            self.slash_controller is not None
            and event.key in {"up", "down", "enter", "tab", "escape"}
            and self.slash_controller(event.key)
        ):
            event.stop()
            event.prevent_default()
            return
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            value = self.text.strip()
            if value:
                self.post_message(self.Submitted(self, value))
            return
        if event.key in {"shift+enter", "ctrl+enter", "alt+enter", "ctrl+j"}:
            event.stop()
            event.prevent_default()
            self.insert("\n")
            return
        await super()._on_key(event)


class ChatLog(VerticalScroll):
    """可滚动的对话区。"""

    def add_welcome(self, project_root: str, tool_count: int) -> None:
        self.mount(WelcomeCard(project_root, tool_count))
        self.call_after_refresh(self.scroll_home, animate=False)

    def add_message(
        self,
        role: str,
        text: str = "",
        *,
        title: str | None = None,
    ) -> Static:
        label = ROLE_LABELS.get(role, role) if title is None else title

        body = Static(text, markup=False, classes=f"message-body body-{role}")
        parts = []
        if label:
            parts.append(
                Static(
                    label,
                    markup=False,
                    classes=f"message-role role-{role}",
                )
            )
        parts.append(body)

        card = VerticalGroup(*parts, classes=f"message-card card-{role}")
        row = VerticalGroup(card, classes=f"message-row row-{role}")
        self.mount(row)
        self.call_after_refresh(self.scroll_end, animate=False)
        return body

    def update_message(
        self,
        body: Static,
        text: str,
        *,
        role_text: str | None = None,
    ) -> None:
        body.update(text)
        if role_text is not None:
            with suppress(Exception):
                card = body.parent
                if card is not None:
                    card.query_one(".message-role", Static).update(role_text)
        self.scroll_end(animate=False)

    def clear_messages(self) -> None:
        self.remove_children()

    def scroll_to_latest(self) -> None:
        self.scroll_end(animate=False)
