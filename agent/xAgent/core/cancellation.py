# -*- coding: utf-8 -*-
"""线程安全的取消令牌。

UI 层（Textual 工作线程、Web 请求协程等）通过它请求取消当前回合；
core 在流式读取、工具循环的边界检查令牌，并可通过 on_cancel 注册
中断底层阻塞操作的回调（例如关闭 HTTP 响应）。
"""
from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress


class CancellationToken:
    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._callbacks: list[Callable[[], None]] = []

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        with self._lock:
            if self._event.is_set():
                return
            self._event.set()
            callbacks = list(self._callbacks)
            self._callbacks.clear()

        for callback in callbacks:
            with suppress(Exception):
                callback()

    @contextmanager
    def on_cancel(self, callback: Callable[[], None]) -> Iterator[None]:
        """在令牌取消时执行 callback；退出上下文时自动注销。"""
        with self._lock:
            already_cancelled = self._event.is_set()
            if not already_cancelled:
                self._callbacks.append(callback)

        if already_cancelled:
            callback()

        try:
            yield
        finally:
            with self._lock:
                try:
                    self._callbacks.remove(callback)
                except ValueError:
                    pass
