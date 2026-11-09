# -*- coding: utf-8 -*-
"""会话持久化。

每个会话保存为一个目录：

    <project_root>/.agents/sessions/<session_id>/
    ├── session.json   # 元数据 + 完整消息快照
    └── events.jsonl   # 追加式事件日志（一轮、工具、压缩、AGENTS.md 注入等）

该模块只负责读写文件，不依赖 Textual，也不包含业务提示词。
"""
from __future__ import annotations

import json
import os
import re
import secrets
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

SESSION_DIRNAME = Path(".agents") / "sessions"
SESSION_FILENAME = "session.json"
EVENTS_FILENAME = "events.jsonl"
SCHEMA_VERSION = 1

_SESSION_ID_RE = re.compile(r"^[0-9A-Za-z_-]{1,80}$")


@dataclass(frozen=True, slots=True)
class SessionInfo:
    id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int
    turn_count: int
    path: Path


class SessionStore:
    def __init__(
        self,
        project_root: str | Path,
        directory: str | Path = SESSION_DIRNAME,
    ) -> None:
        root = Path(project_root).expanduser().resolve()
        path = Path(directory).expanduser()
        self._directory = path if path.is_absolute() else root / path

    @property
    def directory(self) -> Path:
        return self._directory

    def new_id(self, now: datetime | None = None) -> str:
        base = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
        candidate = f"{base}-{secrets.token_hex(2)}"
        index = 1
        while self.session_path(candidate).exists():
            candidate = f"{base}-{secrets.token_hex(2)}-{index}"
            index += 1
        return candidate

    def session_path(self, session_id: str) -> Path:
        return self._directory / _safe_id(session_id)

    def exists(self, session_id: str) -> bool:
        return (self.session_path(session_id) / SESSION_FILENAME).is_file()

    def save(
        self,
        session_id: str,
        *,
        messages: Sequence[Mapping[str, Any]],
        created_at: str,
        updated_at: str,
        title: str,
        turn_count: int,
        agents_md_injected: bool,
    ) -> Path:
        directory = self.session_path(session_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / SESSION_FILENAME
        temp = directory / f".{SESSION_FILENAME}.tmp"
        payload = {
            "schema_version": SCHEMA_VERSION,
            "id": session_id,
            "title": title,
            "created_at": created_at,
            "updated_at": updated_at,
            "message_count": len(messages),
            "turn_count": turn_count,
            "agents_md_injected": bool(agents_md_injected),
            "messages": [dict(message) for message in messages],
        }
        try:
            with temp.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(temp, path)
        finally:
            with suppress(OSError):
                if temp.exists():
                    temp.unlink()
        return path

    def load(self, session_id: str) -> dict[str, Any]:
        path = self.session_path(session_id) / SESSION_FILENAME
        if not path.is_file():
            raise FileNotFoundError(f"会话不存在: {session_id}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"会话文件无法读取: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("会话文件格式异常")
        messages = data.get("messages")
        if not isinstance(messages, list) or not all(
            isinstance(item, dict) for item in messages
        ):
            raise ValueError("会话文件缺少有效的 messages")
        data["messages"] = messages
        return data

    def list(self) -> list[SessionInfo]:
        if not self._directory.exists():
            return []
        infos: list[SessionInfo] = []
        for path in self._directory.glob(f"*/{SESSION_FILENAME}"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            session_id = str(data.get("id") or path.parent.name)
            if _SESSION_ID_RE.fullmatch(session_id) is None:
                continue
            messages = data.get("messages")
            infos.append(
                SessionInfo(
                    id=session_id,
                    title=str(data.get("title") or "未命名会话"),
                    created_at=str(data.get("created_at") or ""),
                    updated_at=str(data.get("updated_at") or ""),
                    message_count=int(data.get("message_count") or 0),
                    turn_count=int(data.get("turn_count") or 0),
                    path=path.parent,
                )
            )
        infos.sort(key=lambda item: (item.updated_at, item.id), reverse=True)
        return infos

    def append_event(
        self,
        session_id: str,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
        *,
        timestamp: str | None = None,
    ) -> None:
        directory = self.session_path(session_id)
        directory.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "type": event_type,
        }
        if payload:
            record["payload"] = dict(payload)
        with (directory / EVENTS_FILENAME).open(
            "a", encoding="utf-8", newline="\n"
        ) as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def delete(self, session_id: str) -> None:
        directory = self.session_path(session_id)
        if not directory.is_dir():
            return
        import shutil

        shutil.rmtree(directory)


def _safe_id(session_id: str) -> str:
    value = str(session_id).strip()
    if _SESSION_ID_RE.fullmatch(value) is None:
        raise ValueError(f"非法会话编号: {session_id}")
    return value


def make_title(messages: Sequence[Mapping[str, Any]], limit: int = 60) -> str:
    for message in messages:
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        text = " ".join(content.split())
        if not text:
            continue
        return text[:limit] + ("…" if len(text) > limit else "")
    return "未命名会话"


__all__ = [
    "EVENTS_FILENAME",
    "SESSION_DIRNAME",
    "SESSION_FILENAME",
    "SessionInfo",
    "SessionStore",
    "make_title",
]
