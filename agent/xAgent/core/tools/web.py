# -*- coding: utf-8 -*-
"""网页读取工具：调用本地 curl 获取 HTML，再用 trafilatura 提取 Markdown 正文。"""
from __future__ import annotations

import locale
import re
import shutil
import subprocess
from typing import Any
from urllib.parse import urlparse

from .registry import Tool

FETCH_TIMEOUT_SECONDS = 20
CONNECT_TIMEOUT_SECONDS = 8
MAX_DOWNLOAD_BYTES = 5 * 1024 * 1024
MAX_MARKDOWN_CHARS = 50_000

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 xAgent-fetchWeb/0.1"
)
_META_CHARSET_RE = re.compile(
    rb"""<meta[^>]+charset\s*=\s*["']?\s*([a-zA-Z0-9._-]+)""",
    re.IGNORECASE,
)


def _decode_output(data: bytes | str) -> str:
    if isinstance(data, str):
        return data
    for enc in ("utf-8", locale.getpreferredencoding(False), "gbk"):
        if not enc:
            continue
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def _validate_url(raw: Any) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("缺少参数 url 或 url 不是非空字符串")

    url = raw.strip()
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("url 只支持 http:// 或 https:// 地址")
    if not parsed.netloc:
        raise ValueError(f"url 不是有效的网页地址: {url}")
    return url


def _decode_html(data: bytes) -> str:
    if not data:
        raise ValueError("网页响应为空")

    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig", errors="replace")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")

    encodings: list[str] = []
    match = _META_CHARSET_RE.search(data[:4096])
    if match:
        declared = match.group(1).decode("ascii", errors="ignore").lower()
        if declared not in {"iso-8859-1", "latin-1", "windows-1252"}:
            encodings.append(declared)
    encodings.extend(["utf-8", "gb18030", "gbk", "latin-1"])

    tried: set[str] = set()
    for enc in encodings:
        if not enc or enc in tried:
            continue
        tried.add(enc)
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def _extract_markdown(html: str, url: str) -> str:
    try:
        import trafilatura
    except ImportError as exc:
        raise ValueError("缺少 trafilatura 依赖，请执行: pip install trafilatura") from exc

    try:
        markdown = trafilatura.extract(
            html,
            url=url,
            output_format="markdown",
            include_comments=False,
            include_tables=True,
            include_links=True,
            include_images=False,
            include_formatting=True,
            favor_precision=True,
            deduplicate=True,
        )
    except Exception as exc:
        raise ValueError(f"HTML 解析或正文提取失败: {exc}") from exc

    if not markdown or not markdown.strip():
        raise ValueError("未能从网页中提取到正文（可能是脚本页、登录页或非 HTML 内容）")
    return markdown.strip()


def _truncate_markdown(markdown: str) -> str:
    if len(markdown) <= MAX_MARKDOWN_CHARS:
        return markdown

    cut = markdown.rfind("\n", 0, MAX_MARKDOWN_CHARS)
    if cut < MAX_MARKDOWN_CHARS // 2:
        cut = MAX_MARKDOWN_CHARS
    return markdown[:cut].rstrip() + "\n\n... [正文过长，已截断]"


def fetch_web(args: dict[str, Any]) -> str:
    url = _validate_url(args.get("url") if isinstance(args, dict) else None)

    curl = shutil.which("curl") or shutil.which("curl.exe")
    if not curl:
        raise ValueError("未找到本地 curl 程序，请先安装 curl 并确保其在 PATH 中")

    command = [
        curl,
        "--fail",
        "--silent",
        "--show-error",
        "--location",
        "--compressed",
        "--globoff",
        "--proto",
        "=http,https",
        "--proto-redir",
        "=http,https",
        "--max-redirs",
        "5",
        "--connect-timeout",
        str(CONNECT_TIMEOUT_SECONDS),
        "--max-time",
        str(FETCH_TIMEOUT_SECONDS),
        "--max-filesize",
        str(MAX_DOWNLOAD_BYTES),
        "--user-agent",
        _USER_AGENT,
        "--",
        url,
    ]

    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            check=False,
            timeout=FETCH_TIMEOUT_SECONDS + 5,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"获取网页超时（超过 {FETCH_TIMEOUT_SECONDS} 秒）: {url}") from exc
    except OSError as exc:
        raise ValueError(f"无法启动 curl: {exc}") from exc

    if proc.returncode == 28:
        raise ValueError(f"获取网页超时（超过 {FETCH_TIMEOUT_SECONDS} 秒）: {url}")
    if proc.returncode != 0:
        reason = _decode_output(proc.stderr).strip()
        raise ValueError(f"获取网页失败（curl 退出码 {proc.returncode}）: {reason or url}")

    data = proc.stdout if isinstance(proc.stdout, bytes) else proc.stdout.encode("utf-8")
    if len(data) > MAX_DOWNLOAD_BYTES:
        raise ValueError(f"网页内容过大（超过 {MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB）: {url}")

    html = _decode_html(data)
    markdown = _truncate_markdown(_extract_markdown(html, url))
    return f"URL: {url}\n\n{markdown}"


def build_web_tools() -> list[Tool]:
    return [
        Tool(
            name="fetchWeb",
            description=(
                "获取指定网页的正文并转换为 Markdown。通过本地 curl 下载 HTML，"
                "再用 trafilatura 提取标题、段落、列表、表格和链接，去除导航栏、广告、页脚等噪声。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "要读取的网页地址，必须以 http:// 或 https:// 开头",
                    }
                },
                "required": ["url"],
            },
            handler=fetch_web,
        )
    ]
