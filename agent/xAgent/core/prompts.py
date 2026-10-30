# -*- coding: utf-8 -*-
"""业务提示词与常量。"""
from __future__ import annotations

from collections.abc import Sequence

from core.skills import Skill

SYSTEM_PROMPT = (
    "你是一个乐于助人的AI助手。你可以调用已注册的工具（日期、闰年、本地文件操作）来完成任务；"
    "执行删除、覆盖等破坏性操作前，请先确认用户意图。\n"
    "请严格按以下格式回复：\n"
    "第一行只输出 ---\n"
    "随后输出对问题的回答正文（可多行）\n"
    "最后一行再只输出 ---"
)

def build_system_prompt(base_prompt: str, skills: Sequence[Skill]) -> str:
    if not skills:
        return base_prompt

    lines = [
        base_prompt.rstrip(),
        "",
        "You have access to the following Agent Skills:",
    ]
    for skill in skills:
        description = " ".join(skill.description.split())
        lines.append(f"- `{skill.name}`: {description}")

    lines.extend(
        [
            "",
            (
                "Use the `loadSkill` tool to load the full instructions of a skill when needed. "
                "You can also load additional files referenced by a skill by providing "
                "the optional `filename` argument."
            ),
        ]
    )
    return "\n".join(lines)


MAX_TOOL_ROUNDS = 8
