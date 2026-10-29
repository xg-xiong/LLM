# -*- coding: utf-8 -*-
"""网络搜索工具：调用百度千帆「百度搜索」API，返回摘要与参考来源。"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

import requests

from core.config import SearchConfig

from .registry import Tool

SEARCH_ENDPOINT = "https://qianfan.baidubce.com/v2/ai_search/web_search"
CONNECT_TIMEOUT = 10
READ_TIMEOUT = 30
TOP_K = 8
MAX_QUERY_UNITS = 72
MAX_SNIPPET_CHARS = 700

_CONTROL_CHARS_RE = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u00ad\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]"
)


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = _CONTROL_CHARS_RE.sub("", str(value))
    return " ".join(text.split())


def _query_units(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1 for char in text)


def _prepare_query(raw: Any) -> tuple[str, bool]:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("缺少参数 query 或 query 不是非空字符串")

    query = " ".join(raw.split())
    if _query_units(query) <= MAX_QUERY_UNITS:
        return query, False

    kept: list[str] = []
    used = 0
    for char in query:
        size = 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
        if used + size > MAX_QUERY_UNITS:
            break
        kept.append(char)
        used += size
    return "".join(kept).rstrip(), True


def _truncate(text: str, limit: int = MAX_SNIPPET_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _api_error(response: requests.Response) -> str:
    detail = ""
    code: Any = None
    try:
        data = response.json()
    except ValueError:
        detail = _clean_text(response.text)[:300]
    else:
        if isinstance(data, dict):
            code = data.get("code")
            detail = _clean_text(data.get("message") or data.get("error") or "")[:300]
        else:
            detail = _clean_text(data)[:300]

    if response.status_code in {401, 403}:
        return (
            "百度千帆搜索鉴权失败，请检查 config.ini 的 [search] "
            f"baidu_qianfan_api_key 是否正确（HTTP {response.status_code}）: "
            f"{detail or '无详细信息'}"
        )
    if response.status_code == 429:
        return f"百度千帆搜索请求过于频繁或额度不足（HTTP 429）: {detail or '无详细信息'}"
    if response.status_code >= 500:
        return f"百度千帆搜索服务暂时不可用（HTTP {response.status_code}）: {detail or '无详细信息'}"

    code_text = f"，错误码 {code}" if code not in (None, "", 0, "0") else ""
    return (
        f"百度千帆搜索请求失败（HTTP {response.status_code}{code_text}）: "
        f"{detail or '无详细信息'}"
    )


def _format_results(query: str, truncated: bool, references: list[Any]) -> str:
    lines = [f"搜索词: {query}"]
    if truncated:
        lines.append(
            f"注意: query 超过 API 长度限制，已截断为前 {MAX_QUERY_UNITS} 个字符"
            "（一个汉字按 2 个字符计）"
        )

    seen: set[str] = set()
    count = 0
    for reference in references:
        if not isinstance(reference, dict):
            continue
        url = _clean_text(reference.get("url"))
        if not url or url in seen:
            continue
        seen.add(url)

        title = _clean_text(reference.get("title") or reference.get("web_anchor")) or "(无标题)"
        snippet = _clean_text(reference.get("snippet") or reference.get("content"))
        date = _clean_text(reference.get("date"))
        website = _clean_text(reference.get("website"))

        count += 1
        lines.extend(["", f"[{count}] {title}", f"URL: {url}"])
        meta = " | ".join(part for part in (website, date) if part)
        if meta:
            lines.append(f"来源信息: {meta}")
        if snippet:
            lines.append(f"摘要: {_truncate(snippet)}")

    if count == 0:
        lines.extend(["", "未找到相关搜索结果。"])
    else:
        lines.insert(1, f"找到 {count} 条参考结果")
    return "\n".join(lines)


def search_web(args: dict[str, Any], config: SearchConfig) -> str:
    api_key = config.baidu_qianfan_api_key.strip()
    if not api_key:
        raise ValueError(
            "未配置百度千帆搜索 API Key，请在 config.ini 的 [search] 小节设置 "
            "baidu_qianfan_api_key"
        )

    query, truncated = _prepare_query(args.get("query") if isinstance(args, dict) else None)
    payload = {
        "messages": [{"role": "user", "content": query}],
        "search_source": "baidu_search_v2",
        "edition": "standard",
        "resource_type_filter": [{"type": "web", "top_k": TOP_K}],
        "query_policy": {"enable_rewrite": True},
        "safe_search": True,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            SEARCH_ENDPOINT,
            json=payload,
            headers=headers,
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
        )
    except requests.Timeout as exc:
        raise ValueError("百度千帆搜索请求超时，请稍后重试") from exc
    except requests.RequestException as exc:
        raise ValueError(f"百度千帆搜索网络请求失败: {exc}") from exc

    if response.status_code != 200:
        raise ValueError(_api_error(response))

    try:
        data = response.json()
    except ValueError as exc:
        raise ValueError("百度千帆搜索 API 返回了无法解析的 JSON 响应") from exc
    if not isinstance(data, dict):
        raise ValueError("百度千帆搜索 API 返回格式异常")

    code = data.get("code")
    if code not in (None, "", 0, "0"):
        message = _clean_text(data.get("message") or data.get("error") or "未知错误")
        raise ValueError(f"百度千帆搜索 API 返回错误（错误码 {code}）: {message}")

    references = data.get("references") or []
    if not isinstance(references, list):
        raise ValueError("百度千帆搜索 API 返回的 references 字段格式异常")
    return _format_results(query, truncated, references)


def build_search_tools(config: SearchConfig) -> list[Tool]:
    def handler(args: dict[str, Any]) -> str:
        return search_web(args, config)

    return [
        Tool(
            name="searchWeb",
            description=(
                "使用百度千帆搜索 API 搜索互联网上的实时信息，返回搜索摘要、参考来源标题和 URL。"
                "适合查询新闻、时事、最新数据等超出模型知识范围的问题。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "搜索关键词或问题，尽量精简；API 最多支持约 72 个字符"
                            "（一个汉字按 2 个字符计）"
                        ),
                    }
                },
                "required": ["query"],
            },
            handler=handler,
        )
    ]
