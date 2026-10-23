# -*- coding: utf-8 -*-
"""core 对外暴露的异常类型。"""


class AgentError(Exception):
    """xAgent core 的基础异常。"""


class AgentBusyError(AgentError):
    """同一个 Agent 实例上一轮尚未结束时又被调用。"""
