# -*- coding: utf-8 -*-
"""系统类工具：日期时间、闰年、当前工作目录。"""
from __future__ import annotations

import locale
import os
import subprocess
from typing import Any

from .registry import Tool


def _decode(data: bytes | str) -> str:
    """子进程输出按系统编码解码：Windows date/time 命令按 OEM/ANSI 代码页输出。"""
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


def get_date(args: dict[str, Any] | None = None) -> str:
    """调用本地 date 命令获取当前日期和时间（不用 python 时间库）。"""
    if os.name == "nt":
        # Windows 下 date 不带参数会进入“输入新的日期”的交互设置，必须加 /t；
        # 时间一并用 time /t 取出
        cmd = ["cmd", "/c", "date /t & time /t"]
    else:
        cmd = ["date"]

    try:
        proc = subprocess.run(cmd, check=False, capture_output=True, timeout=15)
    except subprocess.TimeoutExpired:
        return "执行 date 命令超时"
    except OSError as exc:
        return f"执行 date 命令失败: {exc}"

    out = _decode(proc.stdout).strip()
    if proc.returncode == 0 and out:
        return out

    err = _decode(proc.stderr).strip()
    return f"date 命令返回 {proc.returncode}: {err or out or '无输出'}"


def _parse_year(args: dict[str, Any]) -> int:
    if not isinstance(args, dict) or "year" not in args:
        raise ValueError("缺少参数 year")

    year = args["year"]
    if isinstance(year, bool):  # bool 是 int 子类，需排除
        raise ValueError("year 必须是整数年份")
    if isinstance(year, float):
        if year != int(year):
            raise ValueError("year 必须是整数年份")
        year = int(year)
    if isinstance(year, str):
        year = year.strip()
        if not year or not year.lstrip("-").isdigit():
            raise ValueError(f"year 不是合法整数: {args['year']!r}")
        year = int(year)
    if not isinstance(year, int):
        raise ValueError(f"year 类型不支持: {type(year).__name__}")
    return year


def is_leap_year(args: dict[str, Any]) -> str:
    """按格里高利历规则判断闰年。"""
    year = _parse_year(args)
    leap = (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)
    return f"{year}年{'是' if leap else '不是'}闰年"


def get_current_directory(args: dict[str, Any] | None = None) -> str:
    return os.getcwd()


def build_system_tools() -> list[Tool]:
    return [
        Tool(
            name="getDate",
            description="获取当前电脑的日期和时间，直接调用本地 date 命令得到系统日期与时间",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=get_date,
        ),
        Tool(
            name="isLeapYear",
            description="判断某一年是否是闰年，入参为年份（整数）",
            parameters={
                "type": "object",
                "properties": {
                    "year": {
                        "type": "integer",
                        "description": "要判断的年份，例如 2024",
                    }
                },
                "required": ["year"],
            },
            handler=is_leap_year,
        ),
        Tool(
            name="getCurrentDirectory",
            description="获取当前进程的工作目录（绝对路径）",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=get_current_directory,
        ),
    ]
