# -*- coding: utf-8 -*-
"""上下文长度监控、原始上下文归档与历史检索。

实现刻意保持简单：
- Token 用量优先使用模型接口返回的 usage，缺失时按字符数估算；
- 归档使用项目本地 `.agents/context/*.jsonl`，一行一条原始消息；
- 检索使用普通字符串匹配，不依赖向量数据库或 Embedding。
"""
from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from core.models import TokenUsage

DEFAULT_CONTEXT_WINDOW = 128_000
WARNING_RATIO = 0.6
ARCHIVE_DIRNAME = Path(".agents") / "context"

_ARCHIVE_ID_RE = re.compile(r"^[0-9A-Za-z_-]{1,64}$")


@dataclass(frozen=True, slots=True)
class ContextStatus:
    used_tokens: int
    window_tokens: int
    ratio: float
    warning: bool
    default_window: bool


def estimate_text_tokens(text: str) -> int:
    """粗略估算 token 数。

    中文等非 ASCII 字符约按 1 token/字计算，ASCII 约按 4 字符/token 计算。
    该估算只用于接口没有返回 usage 时的兜底展示与阈值判断。
    """
    if not text:
        return 0
    ascii_count = sum(1 for char in text if ord(char) < 128)
    non_ascii = len(text) - ascii_count
    return max(1, int(ascii_count / 4) + non_ascii)


def estimate_message_tokens(message: Mapping[str, Any]) -> int:
    total = 4  # 单条消息的格式与角色开销
    content = message.get("content")
    if isinstance(content, str):
        total += estimate_text_tokens(content)
    elif content is not None:
        total += estimate_text_tokens(json.dumps(content, ensure_ascii=False))

    for key in ("name", "tool_call_id"):
        value = message.get(key)
        if isinstance(value, str):
            total += estimate_text_tokens(value)

    tool_calls = message.get("tool_calls")
    if tool_calls:
        total += estimate_text_tokens(json.dumps(tool_calls, ensure_ascii=False))
    return total


def estimate_messages_tokens(messages: Sequence[Mapping[str, Any]]) -> int:
    return sum(estimate_message_tokens(message) for message in messages)


def format_transcript(messages: Sequence[Mapping[str, Any]]) -> str:
    """把消息列表渲染成适合在面板中阅读的纯文本。"""
    lines: list[str] = []
    for index, message in enumerate(messages, start=1):
        role = str(message.get("role", "unknown"))
        lines.append(f"[{index}] {role}")
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            lines.append(content)
        elif content is None:
            lines.append("(无文本内容)")
        else:
            lines.append(str(content))

        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, (list, tuple)) and tool_calls:
            lines.append("工具调用:")
            for call in tool_calls:
                if not isinstance(call, Mapping):
                    continue
                fn = call.get("function") or {}
                name = fn.get("name", "") if isinstance(fn, Mapping) else ""
                arguments = fn.get("arguments", "") if isinstance(fn, Mapping) else ""
                lines.append(f"- {name}({arguments})")

        if role == "tool" and message.get("tool_call_id"):
            lines.append(f"tool_call_id: {message['tool_call_id']}")
        lines.append("")
    return "\n".join(lines).strip()


class ContextManager:
    def __init__(
        self,
        project_root: str | Path,
        *,
        window_tokens: int | None = None,
        warning_ratio: float = WARNING_RATIO,
        tool_tokens: int = 0,
        archive_dir: str | Path = ARCHIVE_DIRNAME,
        max_hits: int = 12,
        max_result_chars: int = 6_000,
        snippet_padding: int = 180,
    ) -> None:
        root = Path(project_root).expanduser().resolve()
        archive_path = Path(archive_dir).expanduser()
        self._archive_dir = (
            archive_path if archive_path.is_absolute() else root / archive_path
        )
        self._max_hits = max(1, int(max_hits))
        self._max_result_chars = max(1, int(max_result_chars))
        self._snippet_padding = max(0, int(snippet_padding))
        if window_tokens is not None and window_tokens > 0:
            self._window_tokens = int(window_tokens)
            self._default_window = False
        else:
            self._window_tokens = DEFAULT_CONTEXT_WINDOW
            self._default_window = True
        self._warning_ratio = warning_ratio
        self._tool_tokens = max(0, tool_tokens)
        self._api_tokens: int | None = None

    @property
    def archive_dir(self) -> Path:
        return self._archive_dir

    @property
    def window_tokens(self) -> int:
        return self._window_tokens

    @property
    def default_window(self) -> bool:
        return self._default_window

    def set_tool_tokens(self, tokens: int) -> None:
        self._tool_tokens = max(0, tokens)

    def estimate_usage(self, messages: Sequence[Mapping[str, Any]]) -> int:
        return estimate_messages_tokens(messages) + self._tool_tokens

    def note_api_usage(self, usage: TokenUsage | None) -> None:
        if usage is not None and usage.total_tokens > 0:
            self._api_tokens = usage.total_tokens
        else:
            self._api_tokens = None

    def reset_api_usage(self) -> None:
        self._api_tokens = None

    def status(self, messages: Sequence[Mapping[str, Any]]) -> ContextStatus:
        used = self._api_tokens
        if used is None:
            used = self.estimate_usage(messages)
        ratio = used / self._window_tokens if self._window_tokens else 0.0
        return ContextStatus(
            used_tokens=used,
            window_tokens=self._window_tokens,
            ratio=ratio,
            warning=ratio >= self._warning_ratio,
            default_window=self._default_window,
        )

    # ------------------------------------------------------------------ #
    # 归档
    # ------------------------------------------------------------------ #
    def new_archive_id(self, now: datetime | None = None) -> str:
        base = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
        candidate = base
        index = 1
        while (self._archive_dir / f"{candidate}.jsonl").exists():
            candidate = f"{base}-{index}"
            index += 1
        return candidate

    def save_archive(
        self,
        messages: Sequence[Mapping[str, Any]],
        archive_id: str,
    ) -> Path:
        """把原始消息按 JSONL 保存；成功返回路径，失败抛出 OSError。"""
        self._archive_dir.mkdir(parents=True, exist_ok=True)
        path = self._archive_dir / f"{archive_id}.jsonl"
        temp = self._archive_dir / f".{archive_id}.jsonl.tmp"
        try:
            with temp.open("w", encoding="utf-8", newline="\n") as handle:
                for message in messages:
                    handle.write(json.dumps(message, ensure_ascii=False) + "\n")
            os.replace(temp, path)
        finally:
            with suppress(OSError):
                if temp.exists():
                    temp.unlink()
        return path

    def list_archive_ids(self) -> list[str]:
        if not self._archive_dir.exists():
            return []
        return sorted(path.stem for path in self._archive_dir.glob("*.jsonl"))

    # ------------------------------------------------------------------ #
    # 历史检索
    # ------------------------------------------------------------------ #
    def search(self, text: str, archive_id: str | None = None) -> str:
        query = text.strip()
        if not query:
            return "检索失败：text 参数不能为空。"

        if archive_id:
            safe_id = _sanitize_archive_id(archive_id)
            if safe_id is None:
                return f"检索失败：归档编号不合法：{archive_id}"
            path = self._archive_dir / f"{safe_id}.jsonl"
            if not path.exists():
                return f"未找到编号为 {safe_id} 的上下文归档。"
            files = [path]
        else:
            if not self._archive_dir.exists():
                return "当前还没有任何上下文归档，无法检索历史信息。"
            files = sorted(self._archive_dir.glob("*.jsonl"))
            if not files:
                return "当前还没有任何上下文归档，无法检索历史信息。"

        hits: list[str] = []
        total_chars = 0
        truncated = False
        matched_files: set[str] = set()

        for path in files:
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            archive = path.stem
            for line_no, line in enumerate(lines, start=1):
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(message, Mapping):
                    continue
                haystack = _searchable_text(message)
                positions = _find_positions(haystack, query)
                for position in positions:
                    snippet = _make_snippet(
                        haystack,
                        position,
                        len(query),
                        self._snippet_padding,
                    )
                    role = str(message.get("role", "unknown"))
                    entry = (
                        f"[归档 {archive} · 第 {line_no} 条消息 · role={role}]\n"
                        f"{snippet}"
                    )
                    if (
                        total_chars + len(entry) > self._max_result_chars
                        or len(hits) >= self._max_hits
                    ):
                        truncated = True
                        break
                    hits.append(entry)
                    matched_files.add(archive)
                    total_chars += len(entry)
                if truncated:
                    break
            if truncated:
                break

        if not hits:
            scope = f"归档 {archive_id}" if archive_id else "所有历史归档"
            return f"在{scope}中未找到包含 {query!r} 的内容。"

        header = (
            f"在 {len(matched_files)} 个归档中找到 {len(hits)} 处匹配"
            f"（检索词：{query!r}）"
        )
        if archive_id:
            header = f"在归档 {_sanitize_archive_id(archive_id)} 中找到 {len(hits)} 处匹配"
        if truncated:
            header += "\n结果较多，已按相关性与长度截断，如需更多请提供更具体的关键词或归档编号。"
        return header + "\n\n" + "\n\n".join(hits)


def _sanitize_archive_id(archive_id: str) -> str | None:
    value = archive_id.strip()
    if value.endswith(".jsonl"):
        value = value[:-6]
    return value if _ARCHIVE_ID_RE.fullmatch(value) else None


def _searchable_text(message: Mapping[str, Any]) -> str:
    parts: list[str] = []
    content = message.get("content")
    if isinstance(content, str):
        parts.append(content)
    elif content is not None:
        parts.append(json.dumps(content, ensure_ascii=False))

    for key in ("name", "tool_call_id", "role"):
        value = message.get(key)
        if isinstance(value, str):
            parts.append(value)

    tool_calls = message.get("tool_calls")
    if tool_calls:
        parts.append(json.dumps(tool_calls, ensure_ascii=False))
    return "\n".join(parts)


def _find_positions(haystack: str, query: str, limit: int = 2) -> list[int]:
    if not haystack:
        return []
    lower = haystack.lower()
    query_lower = query.lower()
    positions: list[int] = []
    start = 0
    while len(positions) < limit:
        index = lower.find(query_lower, start)
        if index < 0:
            break
        positions.append(index)
        start = index + max(1, len(query_lower))

    if positions:
        return positions

    # 多关键词输入时退化为“任一关键词命中”，便于用户用空格分隔多个词。
    for token in query.split():
        token_lower = token.lower()
        if not token_lower:
            continue
        index = lower.find(token_lower)
        if index >= 0 and index not in positions:
            positions.append(index)
        if len(positions) >= limit:
            break
    return positions


def _make_snippet(
    haystack: str,
    position: int,
    query_length: int,
    padding: int,
) -> str:
    start = max(0, position - padding)
    end = min(len(haystack), position + max(1, query_length) + padding)
    snippet = haystack[start:end].strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(haystack):
        snippet = snippet + "…"
    return snippet
