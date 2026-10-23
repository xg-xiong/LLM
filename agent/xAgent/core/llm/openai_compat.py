# -*- coding: utf-8 -*-
"""OpenAI 兼容接口的流式客户端（DeepSeek / Ollama / vLLM 等）。

该适配器只依赖 requests，不向 stdout 写任何内容；错误通过 ChatResult
返回，由 UI 层决定如何展示。
"""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from contextlib import nullcontext
from typing import Any

import requests

from core.cancellation import CancellationToken
from core.config import LLMConfig
from core.models import ChatResult

CONNECT_TIMEOUT = 10
READ_TIMEOUT = 120


class OpenAICompatibleClient:
    def __init__(self, config: LLMConfig) -> None:
        self._config = config

    def chat_stream(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]],
        *,
        on_text: Callable[[str], None],
        cancel: CancellationToken | None = None,
    ) -> ChatResult:
        if cancel is not None and cancel.cancelled:
            return ChatResult(ok=False, cancelled=True, error="已取消")

        url = f"{self._config.base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"

        payload = {
            "model": self._config.model_name,
            "messages": list(messages),
            "temperature": self._config.temperature,
            "stream": True,
            "tools": list(tools),
            "tool_choice": "auto",
        }

        try:
            resp = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                stream=True,
            )
        except requests.RequestException:
            return ChatResult(ok=False, error="请检查 base_url 与网络连接")

        if resp.status_code != 200:
            detail = ""
            try:
                detail = resp.json().get("error", {}).get("message", "")
            except (AttributeError, TypeError, ValueError):
                pass
            resp.close()
            return ChatResult(ok=False, error=_status_error(resp.status_code, detail))

        parts: list[str] = []
        raw_lines: list[bytes] = []
        bucket: dict[int, dict[str, Any]] = {}
        saw_sse = False

        guard = cancel.on_cancel(resp.close) if cancel is not None else nullcontext()
        try:
            with guard:
                resp.encoding = resp.encoding or "utf-8"
                for line in resp.iter_lines():
                    if cancel is not None and cancel.cancelled:
                        return ChatResult(ok=False, cancelled=True, error="已取消")

                    if not line.startswith(b"data:"):
                        raw_lines.append(line)
                        continue

                    saw_sse = True
                    data = line[5:].strip()
                    if data == b"[DONE]":
                        break

                    try:
                        choice = json.loads(data)["choices"][0]
                    except (ValueError, KeyError, IndexError):
                        continue

                    delta = choice.get("delta") or {}
                    content = delta.get("content")
                    if content:
                        parts.append(content)
                        on_text(content)
                    for piece in delta.get("tool_calls") or []:
                        if isinstance(piece, dict):
                            _merge_tool_call(bucket, piece)

                if not saw_sse and raw_lines:
                    message = json.loads(
                        b"\n".join(raw_lines).decode("utf-8", errors="replace")
                    )["choices"][0]["message"]
                    _parse_message(message, parts, bucket, on_text)
        except (requests.RequestException, OSError):
            if cancel is not None and cancel.cancelled:
                return ChatResult(ok=False, cancelled=True, error="已取消")
            return ChatResult(ok=False, error="连接中断，请检查 base_url 与网络连接")
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            if cancel is not None and cancel.cancelled:
                return ChatResult(ok=False, cancelled=True, error="已取消")
            return ChatResult(ok=False, error="响应格式异常，无法解析")
        finally:
            resp.close()

        tool_calls = tuple(bucket[i] for i in sorted(bucket))
        return ChatResult(ok=True, content="".join(parts), tool_calls=tool_calls)


def _status_error(status_code: int, detail: str) -> str:
    if status_code == 401:
        return "API Key 无效：请检查 config.ini 中 [llm] 的 api_key 是否已正确填写"
    if status_code == 404:
        return "模型不存在，请检查 model_name"
    if status_code == 429 or status_code >= 500:
        return "服务限流或不可用，请稍后重试"
    return f"请求失败（HTTP {status_code}）：{detail or '请检查 base_url 与网络连接'}"


def _merge_tool_call(bucket: dict[int, dict[str, Any]], piece: Mapping[str, Any]) -> None:
    """把流式 delta 中的 tool_calls 片段按 index 合并成完整调用。"""
    index = piece.get("index", 0)
    slot = bucket.setdefault(
        index,
        {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
    )
    if piece.get("id"):
        slot["id"] = piece["id"]
    if piece.get("type"):
        slot["type"] = piece["type"]
    fn = piece.get("function") or {}
    if fn.get("name"):
        slot["function"]["name"] = fn["name"]
    if fn.get("arguments"):
        slot["function"]["arguments"] += fn["arguments"]


def _parse_message(
    message: Mapping[str, Any],
    parts: list[str],
    bucket: dict[int, dict[str, Any]],
    on_text: Callable[[str], None],
) -> None:
    """从非流式 assistant message 中提取正文与 tool_calls。"""
    content = message.get("content")
    if content:
        parts.append(content)
        on_text(content)
    for piece in message.get("tool_calls") or []:
        if isinstance(piece, dict):
            _merge_tool_call(bucket, piece)
