"""petapi 包：统一的后端 REST 客户端与数据模型。

后续新增后端接口调用（get_pet / search_pets / get_stats 等）都在本包中扩展：
- client.py 添加对应方法（统一信封解包、超时、错误处理）
- types.py 添加对应数据模型
各 MCP 工具（tools/）只负责参数映射与结果呈现，不直接碰 HTTP。
"""

from .client import DEFAULT_BASE_URL, DEFAULT_TIMEOUT, PetApiError, PetClient

__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_TIMEOUT",
    "PetApiError",
    "PetClient",
]