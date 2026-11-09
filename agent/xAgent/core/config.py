# -*- coding: utf-8 -*-
"""配置加载与首次运行生成。

配置来源优先级（高 -> 低）：
1. 环境变量 XAGENT_*（见 README）
2. config.ini 的 [llm] / [search] / [web] / [cli] / [mcp] / [context] /
   [session] / [agent] 段（路径可由 XAGENT_CONFIG 指定）
3. 内置默认值

默认从启动时的工作目录读取 config.ini；文件不存在时由 ensure_config_file()
生成一份带注释的完整模板，core 只负责解析和写文件，不打印提示。
"""
from __future__ import annotations

import configparser
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from core.prompts import MAX_TOOL_ROUNDS

DEFAULT_CONFIG_FILENAME = "config.ini"
DEFAULT_CONFIG_PATH = Path.cwd() / DEFAULT_CONFIG_FILENAME

CONFIG_TEMPLATE = """\
# xAgent 配置文件（首次启动自动生成）
# 修改后需要重启 xAgent 才会生效。不要把真实 API Key 提交到 Git。

[llm]
# OpenAI 兼容接口基础地址（通常以 /v1 结尾）
# DeepSeek 云端: https://api.deepseek.com/v1
# 本地 Ollama:  http://localhost:11434/v1
base_url = https://api.deepseek.com/v1

# 模型名称
model_name = deepseek-flash

# API Key；本地 Ollama 可留空
api_key = your-api-key-here

# 采样温度 0~2
temperature = 0.7

# 模型上下文窗口（tokens）。0 或留空表示使用默认 128k，并在界面中标注「默认」
context_window = 0

# HTTP 连接超时与读取超时（秒）
connect_timeout = 10
read_timeout = 120

[search]
# 百度千帆搜索 API Key（searchWeb 工具使用）
baidu_qianfan_api_key = your-qianfan-api-key-here

# 搜索接口与网络超时（秒）
endpoint = https://qianfan.baidubce.com/v2/ai_search/web_search
connect_timeout = 10
read_timeout = 30

# 单次返回结果数、query 长度限制、单条摘要长度
top_k = 8
max_query_units = 72
max_snippet_chars = 700

[web]
# fetchWeb 工具：curl 下载网页的约束
fetch_timeout = 20
connect_timeout = 8
max_download_bytes = 5242880
max_markdown_chars = 50000

[cli]
# Runcli / getDate 工具：本地命令超时、stdout/stderr 最大保留字符数
timeout_seconds = 30
date_timeout_seconds = 15
max_stream_chars = 10000

[mcp]
# MCP 配置文件名（相对于项目根目录）
config_filename = .mcp.json
# 单个 MCP Server 未单独填写 timeout 时使用的默认值（秒）
default_timeout = 60
# 单个 MCP 工具返回内容的最大字符数
max_output_chars = 50000

[context]
# 上下文使用率达到该比例时提醒并暂停普通输入
warning_ratio = 0.6
# 压缩前原始上下文的归档目录（相对于项目根目录）
archive_dir = .agents/context
# recallContext 单次检索最多返回的命中数与字符数
max_recall_hits = 12
max_recall_result_chars = 6000
snippet_padding = 180

[session]
# 会话保存目录（相对于项目根目录）
directory = .agents/sessions
# 每轮对话 / 工具调用 / 压缩结束后自动保存
auto_save = true

[agent]
# Agent Skills、AGENTS.md 与 .mcp.json 的项目根目录；留空使用启动时工作目录
project_root =

# 单轮对话最多允许的工具调用轮次；0 表示不限制
max_tool_rounds = 100
"""


@dataclass(frozen=True, slots=True)
class LLMConfig:
    base_url: str = "http://localhost:11434/v1"
    model_name: str = "qwen2.5"
    api_key: str = ""
    temperature: float = 0.7
    context_window: int | None = None
    connect_timeout: float = 10.0
    read_timeout: float = 120.0

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)


@dataclass(frozen=True, slots=True)
class SearchConfig:
    baidu_qianfan_api_key: str = ""
    endpoint: str = "https://qianfan.baidubce.com/v2/ai_search/web_search"
    connect_timeout: float = 10.0
    read_timeout: float = 30.0
    top_k: int = 8
    max_query_units: int = 72
    max_snippet_chars: int = 700

    @property
    def has_api_key(self) -> bool:
        return bool(self.baidu_qianfan_api_key)


@dataclass(frozen=True, slots=True)
class WebConfig:
    fetch_timeout: float = 20.0
    connect_timeout: float = 8.0
    max_download_bytes: int = 5 * 1024 * 1024
    max_markdown_chars: int = 50_000


@dataclass(frozen=True, slots=True)
class CLIConfig:
    timeout_seconds: float = 30.0
    date_timeout_seconds: float = 15.0
    max_stream_chars: int = 10_000


@dataclass(frozen=True, slots=True)
class MCPConfig:
    config_filename: str = ".mcp.json"
    default_timeout: float = 60.0
    max_output_chars: int = 50_000


@dataclass(frozen=True, slots=True)
class ContextConfig:
    warning_ratio: float = 0.6
    archive_dir: str = ".agents/context"
    max_recall_hits: int = 12
    max_recall_result_chars: int = 6_000
    snippet_padding: int = 180


@dataclass(frozen=True, slots=True)
class SessionConfig:
    directory: str = ".agents/sessions"
    auto_save: bool = True


@dataclass(frozen=True, slots=True)
class AppConfig:
    llm: LLMConfig
    search: SearchConfig = field(default_factory=SearchConfig)
    web: WebConfig = field(default_factory=WebConfig)
    cli: CLIConfig = field(default_factory=CLIConfig)
    mcp: MCPConfig = field(default_factory=MCPConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    source: Path | None = None
    project_root: Path | None = None
    max_tool_rounds: int = MAX_TOOL_ROUNDS

    @classmethod
    def load(
        cls,
        path: str | Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> AppConfig:
        env = os.environ if env is None else env
        config_path = resolve_config_path(path, env)

        parser = configparser.ConfigParser()
        parser.read(str(config_path), encoding="utf-8-sig")
        llm = _section(parser, "llm")
        search = _section(parser, "search")
        web = _section(parser, "web")
        cli = _section(parser, "cli")
        mcp = _section(parser, "mcp")
        context = _section(parser, "context")
        session = _section(parser, "session")
        agent = _section(parser, "agent")

        temperature = _pick_float(
            env, "XAGENT_TEMPERATURE", llm, "temperature", 0.7
        )
        context_window_raw = _pick(
            env,
            "XAGENT_CONTEXT_WINDOW",
            llm,
            "context_window",
            "0",
        )
        context_window = _positive_int(context_window_raw, 0)
        max_tool_rounds = _non_negative_int(
            _pick(
                env,
                "XAGENT_MAX_TOOL_ROUNDS",
                agent,
                "max_tool_rounds",
                str(MAX_TOOL_ROUNDS),
            ),
            MAX_TOOL_ROUNDS,
        )

        project_root_text = str(
            _pick(env, "XAGENT_PROJECT_ROOT", agent, "project_root", "")
        ).strip()
        project_root = (
            Path(project_root_text).expanduser() if project_root_text else None
        )

        warning_ratio = _pick_float(
            env, "XAGENT_CONTEXT_WARNING_RATIO", context, "warning_ratio", 0.6
        )
        warning_ratio = min(max(warning_ratio, 0.05), 1.0)

        return cls(
            llm=LLMConfig(
                base_url=str(
                    _pick(
                        env,
                        "XAGENT_BASE_URL",
                        llm,
                        "base_url",
                        "http://localhost:11434/v1",
                    )
                ).strip().rstrip("/"),
                model_name=str(
                    _pick(env, "XAGENT_MODEL", llm, "model_name", "qwen2.5")
                ).strip(),
                api_key=str(_pick(env, "XAGENT_API_KEY", llm, "api_key", "")).strip(),
                temperature=temperature,
                context_window=context_window or None,
                connect_timeout=_pick_positive_float(
                    env, "XAGENT_LLM_CONNECT_TIMEOUT", llm, "connect_timeout", 10.0
                ),
                read_timeout=_pick_positive_float(
                    env, "XAGENT_LLM_READ_TIMEOUT", llm, "read_timeout", 120.0
                ),
            ),
            search=SearchConfig(
                baidu_qianfan_api_key=str(
                    _pick(
                        env,
                        "XAGENT_SEARCH_API_KEY",
                        search,
                        "baidu_qianfan_api_key",
                        "",
                    )
                ).strip(),
                endpoint=str(
                    _pick(
                        env,
                        "XAGENT_SEARCH_ENDPOINT",
                        search,
                        "endpoint",
                        "https://qianfan.baidubce.com/v2/ai_search/web_search",
                    )
                ).strip(),
                connect_timeout=_pick_positive_float(
                    env, "XAGENT_SEARCH_CONNECT_TIMEOUT", search, "connect_timeout", 10.0
                ),
                read_timeout=_pick_positive_float(
                    env, "XAGENT_SEARCH_READ_TIMEOUT", search, "read_timeout", 30.0
                ),
                top_k=_pick_positive_int(env, "XAGENT_SEARCH_TOP_K", search, "top_k", 8),
                max_query_units=_pick_positive_int(
                    env, "XAGENT_SEARCH_MAX_QUERY_UNITS", search, "max_query_units", 72
                ),
                max_snippet_chars=_pick_positive_int(
                    env,
                    "XAGENT_SEARCH_MAX_SNIPPET_CHARS",
                    search,
                    "max_snippet_chars",
                    700,
                ),
            ),
            web=WebConfig(
                fetch_timeout=_pick_positive_float(
                    env, "XAGENT_WEB_FETCH_TIMEOUT", web, "fetch_timeout", 20.0
                ),
                connect_timeout=_pick_positive_float(
                    env, "XAGENT_WEB_CONNECT_TIMEOUT", web, "connect_timeout", 8.0
                ),
                max_download_bytes=_pick_positive_int(
                    env,
                    "XAGENT_WEB_MAX_DOWNLOAD_BYTES",
                    web,
                    "max_download_bytes",
                    5 * 1024 * 1024,
                ),
                max_markdown_chars=_pick_positive_int(
                    env,
                    "XAGENT_WEB_MAX_MARKDOWN_CHARS",
                    web,
                    "max_markdown_chars",
                    50_000,
                ),
            ),
            cli=CLIConfig(
                timeout_seconds=_pick_positive_float(
                    env, "XAGENT_CLI_TIMEOUT", cli, "timeout_seconds", 30.0
                ),
                date_timeout_seconds=_pick_positive_float(
                    env,
                    "XAGENT_CLI_DATE_TIMEOUT",
                    cli,
                    "date_timeout_seconds",
                    15.0,
                ),
                max_stream_chars=_pick_positive_int(
                    env,
                    "XAGENT_CLI_MAX_STREAM_CHARS",
                    cli,
                    "max_stream_chars",
                    10_000,
                ),
            ),
            mcp=MCPConfig(
                config_filename=str(
                    _pick(
                        env,
                        "XAGENT_MCP_CONFIG",
                        mcp,
                        "config_filename",
                        ".mcp.json",
                    )
                ).strip()
                or ".mcp.json",
                default_timeout=_pick_positive_float(
                    env, "XAGENT_MCP_TIMEOUT", mcp, "default_timeout", 60.0
                ),
                max_output_chars=_pick_positive_int(
                    env,
                    "XAGENT_MCP_MAX_OUTPUT_CHARS",
                    mcp,
                    "max_output_chars",
                    50_000,
                ),
            ),
            context=ContextConfig(
                warning_ratio=warning_ratio,
                archive_dir=str(
                    _pick(env, "XAGENT_CONTEXT_DIR", context, "archive_dir", ".agents/context")
                ).strip()
                or ".agents/context",
                max_recall_hits=_pick_positive_int(
                    env,
                    "XAGENT_RECALL_MAX_HITS",
                    context,
                    "max_recall_hits",
                    12,
                ),
                max_recall_result_chars=_pick_positive_int(
                    env,
                    "XAGENT_RECALL_MAX_CHARS",
                    context,
                    "max_recall_result_chars",
                    6_000,
                ),
                snippet_padding=_pick_positive_int(
                    env, "XAGENT_RECALL_SNIPPET_PADDING", context, "snippet_padding", 180
                ),
            ),
            session=SessionConfig(
                directory=str(
                    _pick(env, "XAGENT_SESSION_DIR", session, "directory", ".agents/sessions")
                ).strip()
                or ".agents/sessions",
                auto_save=_pick_bool(
                    env, "XAGENT_SESSION_AUTO_SAVE", session, "auto_save", True
                ),
            ),
            source=config_path.resolve(),
            project_root=project_root,
            max_tool_rounds=max_tool_rounds,
        )


def resolve_config_path(
    path: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> Path:
    env = os.environ if env is None else env
    raw = path or env.get("XAGENT_CONFIG") or (Path.cwd() / DEFAULT_CONFIG_FILENAME)
    return Path(raw).expanduser()


def ensure_config_file(
    path: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[Path, bool]:
    """确保配置文件存在；返回 (路径, 是否新建)。已存在时绝不覆盖。"""
    config_path = resolve_config_path(path, env)
    if config_path.exists():
        return config_path, False

    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(CONFIG_TEMPLATE)
    return config_path, True


def _section(parser: configparser.ConfigParser, name: str) -> Mapping[str, str]:
    return parser[name] if parser.has_section(name) else {}


def _pick(
    env: Mapping[str, str],
    env_key: str,
    section: Mapping[str, str],
    config_key: str,
    default: str,
) -> str:
    if env.get(env_key):
        return env[env_key]
    value = section.get(config_key) if section else None
    return default if value is None else value


def _pick_float(
    env: Mapping[str, str],
    env_key: str,
    section: Mapping[str, str],
    config_key: str,
    default: float,
) -> float:
    raw = _pick(env, env_key, section, config_key, str(default))
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _pick_positive_float(
    env: Mapping[str, str],
    env_key: str,
    section: Mapping[str, str],
    config_key: str,
    default: float,
) -> float:
    value = _pick_float(env, env_key, section, config_key, default)
    return value if value > 0 else default


def _pick_positive_int(
    env: Mapping[str, str],
    env_key: str,
    section: Mapping[str, str],
    config_key: str,
    default: int,
) -> int:
    raw = _pick(env, env_key, section, config_key, str(default))
    return _positive_int(raw, default)


def _pick_bool(
    env: Mapping[str, str],
    env_key: str,
    section: Mapping[str, str],
    config_key: str,
    default: bool,
) -> bool:
    raw = str(_pick(env, env_key, section, config_key, str(default))).strip().lower()
    if raw in {"1", "true", "yes", "on", "y"}:
        return True
    if raw in {"0", "false", "no", "off", "n"}:
        return False
    return default


def _positive_int(raw: object, default: int) -> int:
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _non_negative_int(raw: object, default: int) -> int:
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return value if value >= 0 else default
