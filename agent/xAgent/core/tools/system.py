# -*- coding: utf-8 -*-
"""系统类工具：日期时间、闰年、当前工作目录、本地 CLI 调用。"""
from __future__ import annotations

import json
import locale
import os
import subprocess
from typing import Any

from .registry import Tool

CLI_TIMEOUT_SECONDS = 30
CLI_MAX_STREAM_CHARS = 10_000


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


def _parse_cli_args(args: dict[str, Any]) -> tuple[str, list[str]]:
    if not isinstance(args, dict):
        raise ValueError("Runcli 参数必须是对象")
    command = args.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ValueError("缺少参数 command 或 command 不是非空字符串")

    raw_args = args.get("args", [])
    if raw_args is None:
        raw_args = []
    if not isinstance(raw_args, list):
        raise ValueError("args 必须是参数列表")
    if any(isinstance(item, (dict, list)) for item in raw_args):
        raise ValueError("args 的每个元素都必须是字符串")

    return command.strip(), [item if isinstance(item, str) else str(item) for item in raw_args]


def _truncate_cli_stream(text: str, label: str) -> tuple[str, str | None]:
    if len(text) <= CLI_MAX_STREAM_CHARS:
        return text, None
    note = (
        f"{label} 已截断：仅显示前 {CLI_MAX_STREAM_CHARS} 个字符"
        f"（原始 {len(text)} 个字符）"
    )
    return text[:CLI_MAX_STREAM_CHARS].rstrip(), note


def _format_cli_result(
    command: str,
    cli_args: list[str],
    returncode: int | None,
    stdout: str,
    stderr: str,
    timed_out: bool = False,
) -> str:
    stdout, stdout_note = _truncate_cli_stream(stdout, "stdout")
    stderr, stderr_note = _truncate_cli_stream(stderr, "stderr")

    lines = [
        f"命令: {command}",
        f"参数: {json.dumps(cli_args, ensure_ascii=False)}",
    ]
    if timed_out:
        lines.append(f"退出码: 无（执行超过 {CLI_TIMEOUT_SECONDS} 秒，已强制终止）")
    else:
        lines.append(f"退出码: {returncode}")
    lines.extend(
        [
            "标准输出:",
            stdout.rstrip() or "(空)",
            "标准错误:",
            stderr.rstrip() or "(空)",
        ]
    )

    notes = [note for note in (stdout_note, stderr_note) if note]
    if notes:
        lines.extend(["", *notes])
    return "\n".join(lines)


def run_cli(args: dict[str, Any]) -> str:
    command, cli_args = _parse_cli_args(args)
    try:
        proc = subprocess.run(
            [command, *cli_args],
            check=False,
            capture_output=True,
            timeout=CLI_TIMEOUT_SECONDS,
            stdin=subprocess.DEVNULL,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        result = _format_cli_result(
            command,
            cli_args,
            None,
            _decode(exc.stdout or b""),
            _decode(exc.stderr or b""),
            timed_out=True,
        )
        raise ValueError(f"命令执行超时\n{result}") from exc
    except FileNotFoundError as exc:
        raise ValueError(
            f"未找到命令 {command!r}，请确认程序已安装并可通过 PATH 找到"
        ) from exc
    except PermissionError as exc:
        raise ValueError(f"没有权限执行命令 {command!r}: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"执行命令 {command!r} 失败: {exc}") from exc

    return _format_cli_result(
        command,
        cli_args,
        proc.returncode,
        _decode(proc.stdout),
        _decode(proc.stderr),
    )


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
        Tool(
            name="Runcli",
            description=(
                "在本机执行任意已安装的命令行程序（CLI）。command 是程序名或可执行文件路径，"
                "args 是参数列表；通过 shell=False 执行，不经过 Shell 拼接。"
                "返回 stdout、stderr 和退出码，命令以运行 xAgent 的当前用户权限执行。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": (
                            "要执行的程序名或可执行文件路径，例如 python、git、node、ffmpeg"
                        ),
                    },
                    "args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "命令行参数列表，例如 ['--version']；没有参数时传 []",
                    },
                },
                "required": ["command", "args"],
            },
            handler=run_cli,
        ),
    ]
