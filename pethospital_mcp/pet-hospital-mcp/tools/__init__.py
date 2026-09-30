"""工具注册模块：汇总所有 MCP 工具并挂载到 MCPServer。

扩展点（后续全量功能）：
1. 在 tools/ 下新建文件，如 get_pet.py
2. 在文件内定义 make_handler(client) -> async 函数（带参数类型注解与中文 docstring）
3. 在本文件 ALL_TOOL_FACTORIES 列表中追加一项
4. server.py 无需改动（register_tools 统一注册）
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from mcp.server import MCPServer

from petapi import PetClient

from .add_pet import make_handler as _make_add_pet
from .list_pets import make_handler as _make_list_pets

# 后续新增工具时在此追加（列表顺序即 tools/list 的确定性返回顺序）
ALL_TOOL_FACTORIES: list[Callable[[PetClient], Callable[..., Awaitable[Any]]]] = [
    _make_list_pets,
    _make_add_pet,
]


def register_tools(mcp: MCPServer, upstream: str, timeout: float) -> None:
    """创建共享后端客户端，并将全部工具注册到 MCPServer。"""
    client = PetClient(base_url=upstream, timeout=timeout)
    for factory in ALL_TOOL_FACTORIES:
        mcp.tool()(factory(client))


__all__ = [
    "ALL_TOOL_FACTORIES",
    "register_tools",
]