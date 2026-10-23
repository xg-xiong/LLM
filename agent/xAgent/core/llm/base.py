# -*- coding: utf-8 -*-
"""LLM 客户端端口（Port）。

core 只依赖这个协议，不依赖具体 SDK；未来的其他模型后端
（Anthropic、本地推理服务等）只需实现同样的 chat_stream。
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

from core.cancellation import CancellationToken
from core.models import ChatResult


class ChatClient(Protocol):
    def chat_stream(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]],
        *,
        on_text: Callable[[str], None],
        cancel: CancellationToken | None = None,
    ) -> ChatResult:
        """发起一次流式请求。

        on_text 在收到正文增量时调用；返回最终结果（正文 + tool_calls）。
        """
        ...
