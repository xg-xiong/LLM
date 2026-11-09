# -*- coding: utf-8 -*-
"""对话历史管理。

只保存 OpenAI 兼容的 message 字典，负责快照 / 回滚 / 清空等业务规则，
不涉及任何展示逻辑。
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
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

    def add_system(self, content: str) -> None:
        self._messages.append({"role": "system", "content": content})

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

    def replace_with_summary(self, summary: str) -> None:
        """保留 System Prompt，用压缩摘要替换其余历史消息。"""
        self._messages = [
            {"role": "system", "content": self._system_prompt},
            {
                "role": "user",
                "content": (
                    "以下是此前对话的压缩摘要，请将其视为已经发生的历史上下文，"
                    "并在此基础上继续完成用户的任务。\n\n"
                    f"{summary}"
                ),
            },
        ]

    def snapshot(self) -> list[dict[str, Any]]:
        return list(self._messages)

    def restore(self, snapshot: list[dict[str, Any]]) -> None:
        self._messages[:] = snapshot

    def replace_messages(self, messages: Sequence[Mapping[str, Any]]) -> None:
        """恢复完整历史；始终保证第一条是当前 System Prompt。"""
        restored = [dict(message) for message in messages]
        if not restored or restored[0].get("role") != "system":
            restored.insert(0, {"role": "system", "content": self._system_prompt})
        else:
            restored[0] = {"role": "system", "content": self._system_prompt}
        self._messages[:] = restored

    def clear(self) -> None:
        self._messages = [{"role": "system", "content": self._system_prompt}]
