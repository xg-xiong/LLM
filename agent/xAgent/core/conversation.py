# -*- coding: utf-8 -*-
"""对话历史管理。

只保存 OpenAI 兼容的 message 字典，负责快照 / 回滚 / 清空等业务规则，
不涉及任何展示逻辑。
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any


class Conversation:
    def __init__(self, system_prompt: str) -> None:
        self._system_prompt = system_prompt
        self._messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt}
        ]

    @property
    def messages(self) -> list[dict[str, Any]]:
        return list(self._messages)

    def __len__(self) -> int:
        return len(self._messages)

    def add_user(self, text: str) -> None:
        self._messages.append({"role": "user", "content": text})

    def add_assistant(
        self,
        content: str | None,
        tool_calls: Sequence[dict[str, Any]] | None = None,
    ) -> None:
        message: dict[str, Any] = {"role": "assistant", "content": content or None}
        if tool_calls:
            message["tool_calls"] = list(tool_calls)
        self._messages.append(message)

    def add_tool_result(self, tool_call_id: str, output: str) -> None:
        self._messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": output,
            }
        )

    def snapshot(self) -> list[dict[str, Any]]:
        return list(self._messages)

    def restore(self, snapshot: list[dict[str, Any]]) -> None:
        self._messages[:] = snapshot

    def clear(self) -> None:
        self._messages = [{"role": "system", "content": self._system_prompt}]
