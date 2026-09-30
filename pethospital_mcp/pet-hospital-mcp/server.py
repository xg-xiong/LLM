"""宠物医院系统 MCP Server。

把本地宠物医院系统 REST API（pethospital.exe 数据源）封装为 MCP 工具（查询为主，含新增），
通过 Streamable HTTP 对外提供服务。

客户端访问地址：http://127.0.0.1:18080/mcp
"""

from __future__ import annotations

import argparse
import logging

from mcp.server import MCPServer
from mcp.server.caching import CacheHint

from tools import register_tools

logger = logging.getLogger("pet-hospital-mcp")


def build_server(upstream: str, timeout: float) -> MCPServer:
    """装配 MCPServer：注册全部工具并返回实例。

    后续扩充能力（如新增工具）只需在 tools/ 中添加文件，无需改这里。
    """
    mcp = MCPServer(
        name="pet-hospital-mcp",
        title="宠物医院系统 MCP Server",
        version="0.1.0",
        description="把本地宠物医院系统 REST API 封装为 MCP 工具（查询为主，含新增，Streamable HTTP）",
        cache_hints={
            # tools/list 结果不变，允许客户端缓存 60 秒
            "tools/list": CacheHint(ttl_ms=60_000, scope="public"),
        },
    )
    register_tools(mcp, upstream=upstream, timeout=timeout)
    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(description="宠物医院系统 MCP Server（Streamable HTTP）")
    parser.add_argument(
        "-addr",
        default="127.0.0.1:18080",
        help="监听地址 host:port，默认 127.0.0.1:18080",
    )
    parser.add_argument(
        "-upstream",
        default="http://127.0.0.1:8080",
        help="后端 REST 服务地址，默认 http://127.0.0.1:8080",
    )
    parser.add_argument(
        "-timeout",
        type=float,
        default=10.0,
        help="后端请求超时（秒），默认 10",
    )
    args = parser.parse_args()

    host, sep, port = args.addr.rpartition(":")
    if not sep:
        host, port = "127.0.0.1", args.addr
    port = int(port)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    mcp = build_server(upstream=args.upstream, timeout=args.timeout)

    logger.info("MCP Server 启动：http://%s:%d/mcp （后端 %s，timeout=%ss）", host, port, args.upstream, args.timeout)
    mcp.run(
        transport="streamable-http",
        host=host,
        port=port,
        stateless_http=True,
    )


if __name__ == "__main__":
    main()