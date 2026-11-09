# -*- coding: utf-8 -*-
"""业务提示词与常量。"""
from __future__ import annotations

from collections.abc import Sequence

from core.skills import Skill

SYSTEM_PROMPT = (
    "你是一个乐于助人的AI助手。你可以调用已注册的工具（日期、闰年、本地文件操作）来完成任务；"
    "执行删除、覆盖等破坏性操作前，请先确认用户意图。\n"
    "如果任务包含多个步骤，请连续调用工具完成全部步骤后再回复；"
    "除破坏性操作外，不要因为步骤较多而提前停止或反复请求用户确认。\n"
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


COMPACTION_SYSTEM_PROMPT = """你是一名 AI Agent 的上下文管理助手。当前会话即将达到上下文窗口限制，需要将历史对话压缩为一份高质量的工作摘要，以便 Agent 在新的上下文中继续执行任务。

请认真阅读提供的历史上下文，提取对后续工作仍然有价值的信息，并生成一份约 5,000 Tokens 的 Markdown 摘要。

摘要应重点保留以下内容：

1. **用户目标与要求**：用户希望完成什么任务？有哪些必须遵守的约束、偏好和验收条件？
2. **已经完成的工作**：哪些任务已经完成？实现了哪些功能？获得了哪些已经验证的结果？
3. **当前工作状态**：Agent 正在处理什么任务？当前进展到哪一步？是否存在尚未解决的问题？
4. **关键技术信息**：保留重要的文件路径、函数名称、接口定义、配置项、执行命令、错误信息和必要的代码片段。
5. **关键决策与原因**：记录用户和 Agent 已经确定的技术方案，以及重要的设计取舍。
6. **下一步任务**：明确接下来应该执行的操作，以及需要继续验证的事项。

请遵守以下要求：

- 优先保留对后续任务有直接影响的信息，删除寒暄、重复讨论、过时的尝试和无关内容。
- 对已经验证的事实与尚未验证的推测作出明确区分。
- 不要将计划完成的任务描述为已经完成。
- 重要的文件路径、函数名称、配置名称和命令应保留准确原文。
- 对失败的尝试，只保留有助于避免重复错误的信息。
- 如果信息存在冲突，应优先保留用户最新确认的要求，并简要说明仍然存在的冲突。
- 如果某些历史细节无法在摘要中完整保留，可简要说明它们已保存到原始上下文归档中，后续可以通过 `recallContext` 工具重新检索。
- 使用清晰的 Markdown 结构输出摘要，不要附加解释或无关内容。

**最终目标：使一个从未阅读过原始对话的 Agent，仅凭这份摘要，就能够理解当前任务、继承关键决策，并继续开展工作。**"""

MAX_TOOL_ROUNDS = 100
