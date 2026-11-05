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
from textual.widgets import Static, TextArea

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
        yield Static("", id="top-clock", markup=False)

    def on_mount(self) -> None:
        self._update_clock()
        self.set_interval(1, self._update_clock)

    def _update_clock(self) -> None:
        self.query_one("#top-clock", Static).update(datetime.now().strftime("%H:%M:%S"))


class PromptArea(TextArea):
    """多行输入框：Enter 发送，Shift+Enter / Ctrl+J 换行。"""

    class Submitted(Message):
        def __init__(self, prompt: PromptArea, value: str) -> None:
            super().__init__()
            self.prompt = prompt
            self.value = value

    async def _on_key(self, event: events.Key) -> None:
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
