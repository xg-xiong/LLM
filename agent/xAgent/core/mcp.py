# -*- coding: utf-8 -*-
"""MCP（Model Context Protocol）客户端。

读取项目根目录的 `.mcp.json`，使用 MCP Python SDK 连接 stdio / Streamable HTTP
服务器，发现工具并把调用结果转换为 xAgent 的 ToolResult。

MCP SDK 是可选依赖：未安装或单个服务器连接失败时只记录问题，不影响本地工具。
"""
from __future__ import annotations

import asyncio
import atexit
import concurrent.futures
import inspect
import json
import re
import subprocess
import threading
from collections.abc import Mapping
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.config import MCPConfig
from core.models import ToolResult

MCP_CONFIG_FILENAME = ".mcp.json"
DEFAULT_TIMEOUT_SECONDS = 60.0
MAX_OUTPUT_CHARS = 50_000

try:  # MCP Python SDK（1.x / 2.x）
    from mcp import ClientSession, StdioServerParameters
except Exception as exc:  # noqa: BLE001 - SDK 缺失时降级为无 MCP 模式
    ClientSession = None  # type: ignore[assignment]
    StdioServerParameters = None  # type: ignore[assignment]
    _MCP_IMPORT_ERROR: Exception | None = exc
else:
    _MCP_IMPORT_ERROR = None

try:  # MCP 2.x 高层客户端：自动协商 modern / legacy 协议
    from mcp import Client as MCPClient
except Exception:  # noqa: BLE001 - 1.x 没有该客户端，继续走 initialize()
    MCPClient = None  # type: ignore[assignment]

try:
    from mcp.client.stdio import stdio_client
except Exception as exc:  # noqa: BLE001
    stdio_client = None  # type: ignore[assignment]
    _STDIO_IMPORT_ERROR: Exception | None = exc
else:
    _STDIO_IMPORT_ERROR = None

try:
    from mcp.client.streamable_http import streamable_http_client
except Exception:
    try:
        # MCP 1.x 使用 streamablehttp_client 这个名字
        from mcp.client.streamable_http import (
            streamablehttp_client as streamable_http_client,
        )
    except Exception as exc:  # noqa: BLE001
        streamable_http_client = None  # type: ignore[assignment]
        _HTTP_IMPORT_ERROR: Exception | None = exc
    else:
        _HTTP_IMPORT_ERROR = None
else:
    _HTTP_IMPORT_ERROR = None


@dataclass(frozen=True, slots=True)
class MCPServerConfig:
    """单个 MCP Server 的连接配置。"""

    name: str
    transport: str
    command: str = ""
    args: tuple[str, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict)
    cwd: Path | None = None
    url: str = ""
    headers: Mapping[str, str] = field(default_factory=dict)
    timeout: float = DEFAULT_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class MCPToolSpec:
    """从 MCP Server 发现的一个工具。"""

    server: str
    name: str
    description: str
    parameters: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class MCPServerStatus:
    """供 UI 展示的单个 MCP Server 连接状态。"""

    name: str
    state: str = "pending"
    tool_count: int = 0
    error: str = ""


@dataclass(slots=True)
class _SessionState:
    stack: AsyncExitStack
    session: Any


def _field(
    obj: Any,
    snake_name: str,
    camel_name: str | None = None,
    default: Any = None,
) -> Any:
    """兼容 MCP SDK 1.x 的 camelCase 与 2.x 的 snake_case 字段。"""
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        if camel_name and camel_name in obj:
            return obj[camel_name]
        if snake_name in obj:
            return obj[snake_name]
        return default

    value = getattr(obj, snake_name, None)
    if value is None and camel_name:
        value = getattr(obj, camel_name, None)
    return default if value is None else value


def _describe_exception(exc: BaseException) -> str:
    nested = getattr(exc, "exceptions", None)
    if nested:
        messages = []
        for item in nested:
            message = _describe_exception(item)
            if message and message not in messages:
                messages.append(message)
        if messages:
            return "; ".join(messages)

    text = str(exc).strip()
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def _safe_text(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)


def _dump_object(obj: Any) -> str:
    if isinstance(obj, Mapping):
        return _safe_text(obj)

    model_dump = getattr(obj, "model_dump", None)
    if callable(model_dump):
        try:
            return _safe_text(model_dump(by_alias=True, exclude_none=True))
        except (TypeError, ValueError):
            try:
                return _safe_text(model_dump())
            except Exception:  # noqa: BLE001
                pass
    return str(obj)


def _format_resource(resource: Any) -> str:
    uri = _field(resource, "uri", "uri", "")
    mime_type = _field(resource, "mime_type", "mimeType", "unknown")
    text = _field(resource, "text", "text")
    if text is not None:
        return f"[资源 {uri}]\n{text}"

    blob = _field(resource, "blob", "blob")
    if blob is not None:
        size = len(str(blob))
        return f"[二进制资源 {uri}, mime={mime_type}, base64 长度 {size}]"
    return _dump_object(resource)


def _format_content_block(block: Any) -> str:
    block_type = str(_field(block, "type", "type", ""))
    if block_type == "text":
        return str(_field(block, "text", "text", ""))

    if block_type == "image":
        data = _field(block, "data", "data", "")
        mime_type = _field(block, "mime_type", "mimeType", "unknown")
        return f"[图片内容: {mime_type}, base64 长度 {len(str(data))}]"

    if block_type == "audio":
        data = _field(block, "data", "data", "")
        mime_type = _field(block, "mime_type", "mimeType", "unknown")
        return f"[音频内容: {mime_type}, base64 长度 {len(str(data))}]"

    if block_type == "resource":
        return _format_resource(_field(block, "resource", "resource"))

    if block_type == "resource_link":
        uri = _field(block, "uri", "uri", "")
        name = _field(block, "name", "name", "")
        return f"[资源链接: {name or uri}]"

    return _dump_object(block)


async def _list_all_tools(session: Any) -> list[Any]:
    """读取全部分页的 MCP 工具列表，兼容 SDK 1.x / 2.x 的游标参数。"""
    tools: list[Any] = []
    cursor: str | None = None
    seen: set[str] = set()
    page = 0

    while True:
        page += 1
        if cursor is None:
            listing = await session.list_tools()
        else:
            try:
                parameters = inspect.signature(session.list_tools).parameters
            except (TypeError, ValueError):
                break
            if "params" in parameters:
                from mcp import types

                listing = await session.list_tools(
                    params=types.PaginatedRequestParams(cursor=cursor)
                )
            elif "cursor" in parameters:
                listing = await session.list_tools(cursor=cursor)
            else:
                break

        tools.extend(list(_field(listing, "tools", "tools", []) or []))
        next_cursor = _field(listing, "next_cursor", "nextCursor")
        if not next_cursor or str(next_cursor) in seen:
            break
        seen.add(str(next_cursor))
        cursor = str(next_cursor)
        if page >= 100:
            break

    return tools


def _format_call_result(
    result: Any,
    max_output_chars: int = MAX_OUTPUT_CHARS,
) -> tuple[str, bool]:
    """把 CallToolResult 转成给 LLM 的文本，并返回是否为工具级错误。"""
    content = _field(result, "content", "content", []) or []
    parts: list[str] = []
    for block in content:
        text = _format_content_block(block).strip()
        if text:
            parts.append(text)

    structured = _field(result, "structured_content", "structuredContent")
    if structured is not None:
        parts.append(f"结构化数据:\n{_safe_text(structured)}")

    output = "\n\n".join(parts).strip()
    if not output:
        output = "(MCP 工具无返回内容)"
    if len(output) > max_output_chars:
        output = (
            output[:max_output_chars].rstrip()
            + "\n\n... [MCP 工具输出过长，已截断]"
        )

    is_error = bool(_field(result, "is_error", "isError", False))
    return output, is_error


def load_mcp_servers(
    project_root: str | Path,
    config: MCPConfig | None = None,
) -> tuple[list[MCPServerConfig], list[str]]:
    """读取 `<project_root>/.mcp.json`，返回有效配置与问题列表。"""
    config = config or MCPConfig()
    path = Path(project_root) / config.config_filename
    if not path.is_file():
        return [], []

    try:
        raw_text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        return [], [f"无法读取 {path}: {exc}"]

    try:
        data = json.loads(raw_text)
    except ValueError as exc:
        return [], [f"{path} 不是有效的 JSON: {exc}"]

    if not isinstance(data, Mapping):
        return [], [f"{path} 顶层必须是 JSON 对象"]

    servers_raw = data.get("mcpServers")
    if servers_raw is None:
        return [], [f"{path} 缺少 mcpServers 字段"]
    if not isinstance(servers_raw, Mapping):
        return [], [f"{path} 的 mcpServers 必须是对象"]

    configs: list[MCPServerConfig] = []
    issues: list[str] = []
    for raw_name, raw_config in servers_raw.items():
        name = str(raw_name).strip()
        if not name:
            issues.append(f"{path} 中存在空的 MCP Server 名称，已跳过")
            continue
        if not isinstance(raw_config, Mapping):
            issues.append(f"MCP Server `{name}` 配置必须是对象，已跳过")
            continue
        if raw_config.get("disabled") is True:
            continue

        try:
            server_config = _parse_server_config(
                name,
                raw_config,
                path.parent,
                default_timeout=config.default_timeout,
            )
        except ValueError as exc:
            issues.append(f"MCP Server `{name}` 配置无效: {exc}")
            continue
        configs.append(server_config)

    return configs, issues


def _parse_server_config(
    name: str,
    raw: Mapping[str, Any],
    base_dir: Path,
    *,
    default_timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> MCPServerConfig:
    declared = raw.get("type") or raw.get("transport")
    transport = ""
    if declared is not None:
        transport = str(declared).strip().lower().replace("-", "_")

    if transport in {"streamable_http", "streamablehttp", "http"}:
        transport = "streamable_http"
    elif transport == "stdio":
        transport = "stdio"
    elif not transport:
        transport = "streamable_http" if raw.get("url") else "stdio"
    else:
        raise ValueError(f"不支持的 type: {declared}（仅支持 stdio / streamable_http）")

    timeout = _parse_timeout(raw.get("timeout"), default_timeout)
    if transport == "stdio":
        command = raw.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ValueError("stdio 类型必须提供非空 command")

        args_raw = raw.get("args", [])
        if args_raw is None:
            args: list[str] = []
        elif isinstance(args_raw, list):
            args = [str(item) for item in args_raw]
        else:
            raise ValueError("args 必须是字符串数组")

        env_raw = raw.get("env", {})
        env: dict[str, str] = {}
        if env_raw is not None:
            if not isinstance(env_raw, Mapping):
                raise ValueError("env 必须是对象")
            env = {str(key): str(value) for key, value in env_raw.items()}

        cwd_raw = raw.get("cwd")
        cwd = None
        if cwd_raw:
            cwd = Path(str(cwd_raw)).expanduser()
            if not cwd.is_absolute():
                cwd = base_dir / cwd

        return MCPServerConfig(
            name=name,
            transport="stdio",
            command=command.strip(),
            args=tuple(args),
            env=env,
            cwd=cwd,
            timeout=timeout,
        )

    url = raw.get("url")
    if not isinstance(url, str) or not url.strip():
        raise ValueError("streamable_http 类型必须提供非空 url")
    url = url.strip()
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("url 必须以 http:// 或 https:// 开头")

    headers_raw = raw.get("headers", {})
    headers: dict[str, str] = {}
    if headers_raw is not None:
        if not isinstance(headers_raw, Mapping):
            raise ValueError("headers 必须是对象")
        headers = {str(key): str(value) for key, value in headers_raw.items()}

    return MCPServerConfig(
        name=name,
        transport="streamable_http",
        url=url,
        headers=headers,
        timeout=timeout,
    )


def _parse_timeout(raw: Any, default: float = DEFAULT_TIMEOUT_SECONDS) -> float:
    if raw is None:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("timeout 必须是数字") from exc
    return value if value > 0 else default


class MCPManager:
    """管理多个 MCP Server 的连接、工具映射和工具调用。

    所有 MCP 异步操作都在一个后台事件循环线程中执行，对上层保持同步接口。
    """

    def __init__(
        self,
        configs: list[MCPServerConfig],
        issues: list[str] | None = None,
        *,
        max_output_chars: int = MAX_OUTPUT_CHARS,
    ) -> None:
        self._configs = tuple(configs)
        self._config_by_name = {config.name: config for config in configs}
        self._issues = list(issues or [])
        self._tools: list[MCPToolSpec] = []
        self._bindings: dict[str, MCPToolSpec] = {}
        self._states: dict[str, _SessionState] = {}
        self._status: dict[str, MCPServerStatus] = {
            config.name: MCPServerStatus(name=config.name)
            for config in configs
        }
        self._max_output_chars = max(1, int(max_output_chars))
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._close_lock = threading.Lock()
        self._closed = False

    @classmethod
    def from_project_root(
        cls,
        project_root: str | Path,
        config: MCPConfig | None = None,
    ) -> MCPManager:
        config = config or MCPConfig()
        configs, issues = load_mcp_servers(project_root, config)
        return cls(
            configs,
            issues,
            max_output_chars=config.max_output_chars,
        )

    @property
    def servers(self) -> tuple[MCPServerConfig, ...]:
        return self._configs

    @property
    def server_names(self) -> list[str]:
        return [config.name for config in self._configs]

    @property
    def tools(self) -> tuple[MCPToolSpec, ...]:
        return tuple(self._tools)

    @property
    def issues(self) -> list[str]:
        return list(self._issues)

    @property
    def statuses(self) -> tuple[MCPServerStatus, ...]:
        return tuple(self._status[name] for name in self.server_names)

    def bind_tool(self, exposed_name: str, spec: MCPToolSpec) -> None:
        self._bindings[exposed_name] = spec

    def connect_all(self) -> None:
        """连接全部服务器并发现工具；失败写入 issues，不抛出异常。"""
        if not self._configs:
            return
        if _MCP_IMPORT_ERROR is not None:
            message = (
                "未安装 MCP Python SDK，无法连接 MCP Server。"
                "请执行: python -m pip install mcp"
            )
            self._issues.append(message)
            for name in self.server_names:
                self._status[name] = MCPServerStatus(
                    name=name,
                    state="error",
                    error=message,
                )
            return

        try:
            self._start_loop()
        except Exception as exc:  # noqa: BLE001
            message = f"MCP 客户端初始化失败: {_describe_exception(exc)}"
            self._issues.append(message)
            for name in self.server_names:
                self._status[name] = MCPServerStatus(
                    name=name,
                    state="error",
                    error=message,
                )
            return

        for config in self._configs:
            self._status[config.name] = MCPServerStatus(
                name=config.name,
                state="connecting",
            )
            try:
                specs = self._submit(
                    self._connect(config),
                    timeout=config.timeout + 10,
                )
            except concurrent.futures.TimeoutError:
                message = (
                    f"MCP Server `{config.name}` 连接超时"
                    f"（{config.timeout:g} 秒）"
                )
                self._issues.append(message)
                self._status[config.name] = MCPServerStatus(
                    name=config.name,
                    state="error",
                    error=message,
                )
                continue
            except Exception as exc:  # noqa: BLE001 - 单个服务器失败不影响其他服务器
                message = (
                    f"MCP Server `{config.name}` 连接失败: "
                    f"{_describe_exception(exc)}"
                )
                self._issues.append(message)
                self._status[config.name] = MCPServerStatus(
                    name=config.name,
                    state="error",
                    error=message,
                )
                continue
            self._tools.extend(specs)
            self._status[config.name] = MCPServerStatus(
                name=config.name,
                state="connected",
                tool_count=len(specs),
            )

    def call_tool(
        self,
        exposed_name: str,
        arguments: Mapping[str, Any] | None = None,
    ) -> ToolResult:
        """调用 LLM 暴露名称对应的 MCP 工具，返回统一 ToolResult。"""
        spec = self._bindings.get(exposed_name)
        if spec is None:
            return ToolResult(
                output=f"未知的 MCP 工具映射: {exposed_name}",
                is_error=True,
            )

        config = self._config_by_name.get(spec.server)
        timeout = config.timeout if config is not None else DEFAULT_TIMEOUT_SECONDS
        args = dict(arguments or {})
        try:
            result = self._submit(
                self._call_tool(spec, args, timeout),
                timeout=timeout + 10,
            )
        except concurrent.futures.TimeoutError:
            return ToolResult(
                output=(
                    f"MCP 工具 `{spec.server}/{spec.name}` 调用超时"
                    f"（{timeout:g} 秒）"
                ),
                is_error=True,
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                output=(
                    f"MCP 工具 `{spec.server}/{spec.name}` 调用失败: "
                    f"{_describe_exception(exc)}"
                ),
                is_error=True,
            )

        output, is_error = _format_call_result(result, self._max_output_chars)
        if is_error:
            output = (
                f"MCP 工具 `{spec.server}/{spec.name}` 返回错误:\n{output}"
            )
        return ToolResult(output=output, is_error=is_error)

    def close(self) -> None:
        """关闭所有 MCP 会话并停止后台事件循环。可重复调用。"""
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            loop = self._loop
            thread = self._thread
            self._loop = None
            self._thread = None

        if loop is None:
            return

        try:
            future = asyncio.run_coroutine_threadsafe(self._close_all(), loop)
            future.result(timeout=10)
        except Exception:  # noqa: BLE001 - 关闭阶段不再抛出
            pass
        try:
            loop.call_soon_threadsafe(loop.stop)
        except RuntimeError:
            pass
        if thread is not None:
            thread.join(timeout=5)

    def _start_loop(self) -> None:
        if self._loop is not None:
            return

        loop = asyncio.new_event_loop()
        thread = threading.Thread(
            target=self._loop_worker,
            args=(loop,),
            name="xagent-mcp",
            daemon=True,
        )
        self._loop = loop
        self._thread = thread
        thread.start()
        if not self._ready.wait(5):
            raise RuntimeError("MCP 后台事件循环启动超时")
        atexit.register(self.close)

    def _loop_worker(self, loop: asyncio.AbstractEventLoop) -> None:
        asyncio.set_event_loop(loop)
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            try:
                pending = [
                    task for task in asyncio.all_tasks(loop) if not task.done()
                ]
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
            except Exception:  # noqa: BLE001
                pass
            finally:
                loop.close()

    def _submit(self, coroutine: Any, timeout: float) -> Any:
        if self._closed:
            raise RuntimeError("MCP 客户端已关闭")
        loop = self._loop
        if loop is None or not loop.is_running():
            raise RuntimeError("MCP 客户端尚未启动")

        future = asyncio.run_coroutine_threadsafe(coroutine, loop)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise

    async def _connect(self, config: MCPServerConfig) -> list[MCPToolSpec]:
        stack = AsyncExitStack()
        try:
            if MCPClient is not None:
                session = await self._connect_auto(config, stack)
            else:
                session = await self._connect_legacy(config, stack)
            discovered = await _list_all_tools(session)

            specs = []
            for tool in discovered:
                parameters = _field(tool, "input_schema", "inputSchema", {})
                if not isinstance(parameters, Mapping):
                    parameters = {}
                else:
                    parameters = dict(parameters)
                parameters.setdefault("type", "object")
                parameters.setdefault("properties", {})

                specs.append(
                    MCPToolSpec(
                        server=config.name,
                        name=str(_field(tool, "name", "name", "")),
                        description=str(
                            _field(tool, "description", "description", "") or ""
                        ),
                        parameters=parameters,
                    )
                )

            self._states[config.name] = _SessionState(
                stack=stack,
                session=session,
            )
            return specs
        except BaseException as exc:
            close_error = await _close_stack(stack)
            if _is_cancelled(exc) and close_error is not None and not _is_cancelled(
                close_error
            ):
                raise close_error from exc
            raise

    def _make_transport(self, config: MCPServerConfig, stack: AsyncExitStack) -> Any:
        if config.transport == "stdio":
            if stdio_client is None or StdioServerParameters is None:
                raise RuntimeError(
                    f"无法加载 MCP stdio 客户端: "
                    f"{_describe_exception(_STDIO_IMPORT_ERROR or _MCP_IMPORT_ERROR)}"
                )
            params = StdioServerParameters(
                command=config.command,
                args=list(config.args),
                env=dict(config.env) or None,
                cwd=str(config.cwd) if config.cwd is not None else None,
            )
            # 子进程 stderr 不写进 TUI；连接/启动错误仍会通过异常上报。
            stdio_kwargs: dict[str, Any] = {}
            try:
                if "errlog" in inspect.signature(stdio_client).parameters:
                    stdio_kwargs["errlog"] = subprocess.DEVNULL
            except (TypeError, ValueError):
                pass
            return stdio_client(params, **stdio_kwargs)

        if streamable_http_client is None:
            raise RuntimeError(
                f"无法加载 MCP Streamable HTTP 客户端: "
                f"{_describe_exception(_HTTP_IMPORT_ERROR)}"
            )
        kwargs = self._http_transport_kwargs(config, stack)
        return streamable_http_client(config.url, **kwargs)

    async def _connect_auto(
        self,
        config: MCPServerConfig,
        stack: AsyncExitStack,
    ) -> Any:
        if MCPClient is None:
            raise RuntimeError("无法加载 MCP Client")
        transport = self._make_transport(config, stack)
        client = MCPClient(
            transport,
            mode="auto",
            read_timeout_seconds=config.timeout,
        )
        await stack.enter_async_context(client)
        return client.session

    async def _connect_legacy(
        self,
        config: MCPServerConfig,
        stack: AsyncExitStack,
    ) -> Any:
        transport = self._make_transport(config, stack)
        streams = await stack.enter_async_context(transport)
        read_stream, write_stream = streams[0], streams[1]
        if ClientSession is None:
            raise RuntimeError("无法加载 MCP ClientSession")
        session = await stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await session.initialize()
        return session

    def _http_transport_kwargs(
        self,
        config: MCPServerConfig,
        stack: AsyncExitStack,
    ) -> dict[str, Any]:
        if not config.headers or streamable_http_client is None:
            return {}

        try:
            parameters = inspect.signature(streamable_http_client).parameters
        except (TypeError, ValueError):
            return {}

        if "headers" in parameters:
            return {"headers": dict(config.headers)}
        if "http_client" in parameters:
            try:
                import httpx2
            except ImportError:
                return {}
            client = httpx2.AsyncClient(headers=dict(config.headers))
            stack.push_async_callback(client.aclose)
            return {"http_client": client}
        return {}

    async def _call_tool(
        self,
        spec: MCPToolSpec,
        arguments: dict[str, Any],
        timeout: float,
    ) -> Any:
        state = self._states.get(spec.server)
        if state is None:
            config = self._config_by_name.get(spec.server)
            if config is None:
                raise RuntimeError(f"未找到 MCP Server 配置: {spec.server}")
            await self._connect(config)
            state = self._states.get(spec.server)
            if state is None:
                raise RuntimeError(f"MCP Server `{spec.server}` 重新连接失败")

        try:
            return await state.session.call_tool(
                spec.name,
                arguments,
                read_timeout_seconds=timeout,
            )
        except Exception:
            await self._drop(spec.server)
            raise

    async def _drop(self, server: str) -> None:
        state = self._states.pop(server, None)
        if state is not None:
            await _safe_aclose(state.stack)

    async def _close_all(self) -> None:
        for server in list(self._states):
            await self._drop(server)


async def _safe_aclose(stack: AsyncExitStack) -> None:
    try:
        await stack.aclose()
    except BaseException:  # noqa: BLE001 - 关闭异常不应影响调用方
        pass


async def _close_stack(stack: AsyncExitStack) -> BaseException | None:
    try:
        await stack.aclose()
    except BaseException as exc:  # noqa: BLE001 - 返回给调用方判断
        return exc
    return None


def _is_cancelled(exc: BaseException) -> bool:
    if isinstance(exc, asyncio.CancelledError):
        return True
    nested = getattr(exc, "exceptions", None)
    return bool(nested) and all(_is_cancelled(item) for item in nested)


_MAX_NAME_LENGTH = 64
_FUNCTION_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _safe_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_")
    return cleaned or "mcp"


def unique_tool_name(spec: MCPToolSpec, used: set[str]) -> str:
    """为 MCP 工具选择不冲突的 LLM 可见名称。"""
    if _FUNCTION_NAME_RE.fullmatch(spec.name) and spec.name not in used:
        return spec.name

    base = _safe_component(f"{spec.server}__{spec.name}")[:_MAX_NAME_LENGTH]
    candidate = base
    index = 2
    while candidate in used:
        suffix = f"_{index}"
        candidate = base[: _MAX_NAME_LENGTH - len(suffix)] + suffix
        index += 1
    return candidate


__all__ = [
    "MCP_CONFIG_FILENAME",
    "MCPManager",
    "MCPServerConfig",
    "MCPServerStatus",
    "MCPToolSpec",
    "load_mcp_servers",
    "unique_tool_name",
]
