# -*- coding: utf-8 -*-
"""上下文历史检索工具 recallContext。"""
from __future__ import annotations

from typing import Any

from core.context import ContextManager
from core.models import ToolResult

from .registry import Tool


def build_context_tools(manager: ContextManager) -> list[Tool]:
    def recall_context(args: dict[str, Any]) -> str | ToolResult:
        text = args.get("text")
        if not isinstance(text, str) or not text.strip():
            return ToolResult(output="recallContext 参数错误：text 必须是非空字符串", is_error=True)

        archive_id = args.get("id")
        if archive_id is not None and not isinstance(archive_id, str):
            return ToolResult(output="recallContext 参数错误：id 必须是字符串", is_error=True)

        return manager.search(text, archive_id or None)

    return [
        Tool(
            name="recallContext",
            description=(
                "检索此前被压缩并归档的原始对话上下文。当压缩摘要缺少某些历史细节时使用。"
                "text 为要查找的关键词或文本；id 可选，指定归档编号（例如 20261022-153000），"
                "不填则在所有历史归档中检索。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "可选，上下文归档编号；不填则检索所有归档。",
                    },
                    "text": {
                        "type": "string",
                        "description": "必须，要查找的关键词或文本内容。",
                    },
                },
                "required": ["text"],
            },
            handler=recall_context,
        )
    ]
