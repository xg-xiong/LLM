# -*- coding: utf-8 -*-
"""chat3.py: 终端 AI 问答 Agent（OpenAI 兼容接口 + function call）

基于 chat2.py，保留 getDate（调用本地 date 命令）与 isLeapYear（闰年判断），
并新增一组本地文件操作工具：
    获取当前工作目录、列出目录内容、查询文件类型、读取/创建/编辑纯文本文件、
    创建目录、删除目录（支持非空）、删除文件、重命名文件或目录。

用法: python chat3.py
"""
import configparser
import json
import locale
import mimetypes
import os
import shutil
import subprocess
import sys
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent

# 内置中文指令，要求模型按固定格式回复（首行 ---、正文、尾行 ---）
SYSTEM_PROMPT = (
    "你是一个乐于助人的AI助手。你可以调用已注册的工具（日期、闰年、本地文件操作）来完成任务；"
    "执行删除、覆盖等破坏性操作前，请先确认用户意图。\n"
    "请严格按以下格式回复：\n"
    "第一行只输出 ---\n"
    "随后输出对问题的回答正文（可多行）\n"
    "最后一行再只输出 ---"
)

# 单轮提问最多允许的工具调用次数，防止模型反复调用导致死循环
MAX_TOOL_ROUNDS = 8


# --------------------------------------------------------------------------- #
# function call 工具定义与实现
# --------------------------------------------------------------------------- #
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "getDate",
            "description": "获取当前电脑的日期和时间，直接调用本地 date 命令得到系统日期与时间",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "isLeapYear",
            "description": "判断某一年是否是闰年，入参为年份（整数）",
            "parameters": {
                "type": "object",
                "properties": {
                    "year": {
                        "type": "integer",
                        "description": "要判断的年份，例如 2024",
                    }
                },
                "required": ["year"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "getCurrentDirectory",
            "description": "获取当前进程的工作目录（绝对路径）",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listDirectory",
            "description": "列出指定目录下的所有文件和子目录，包含名称、类型和文件大小",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "要列出的目录路径，支持相对路径或绝对路径",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "getFileType",
            "description": "获取指定文件（或目录）的类型，包括扩展名、MIME 类型以及是否为纯文本",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "要查询的文件或目录路径",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "readTextFile",
            "description": "读取指定纯文本文件的完整内容，仅支持文本类文件（如 .txt/.md/.py/.json 等）",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "要读取的纯文本文件路径",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "createFile",
            "description": "在指定目录下按文件名创建新文件，文件已存在时不会覆盖，可选写入初始文本内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {
                        "type": "string",
                        "description": "新文件所在的目录路径，目录必须已存在",
                    },
                    "filename": {
                        "type": "string",
                        "description": "新文件名（只能是文件名，不能包含路径分隔符）",
                    },
                    "content": {
                        "type": "string",
                        "description": "可选的初始文本内容，默认为空",
                    },
                },
                "required": ["directory", "filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "editFile",
            "description": (
                "编辑指定纯文本文件的内容。mode=overwrite 用 content 覆盖整个文件；"
                "mode=append 把 content 追加到文件末尾；mode=replace 把文件中的 old_text 替换为 content"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "要编辑的纯文本文件路径",
                    },
                    "content": {
                        "type": "string",
                        "description": "新内容（overwrite/append）或替换后的内容（replace）",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["overwrite", "append", "replace"],
                        "description": "编辑方式，默认为 overwrite",
                    },
                    "old_text": {
                        "type": "string",
                        "description": "replace 模式下要被替换的原文本",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "createDirectory",
            "description": "创建新目录，会自动创建缺失的上级目录；目标已存在时返回错误",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "要创建的目录路径",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "deleteDirectory",
            "description": "删除指定目录及其中的所有内容（支持非空目录），请谨慎使用",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "要删除的目录路径",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "deleteFile",
            "description": "删除指定文件（不能用于删除目录），请谨慎使用",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "要删除的文件路径",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "renameFileOrDirectory",
            "description": "重命名文件或目录。new_path 只写名称时在同一目录内重命名，也可给出新的完整路径（目标不能已存在）",
            "parameters": {
                "type": "object",
                "properties": {
                    "old_path": {
                        "type": "string",
                        "description": "原文件或目录路径",
                    },
                    "new_path": {
                        "type": "string",
                        "description": "新名称或新路径",
                    },
                },
                "required": ["old_path", "new_path"],
            },
        },
    },
]


def _decode(data):
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


def get_date(args=None):
    """调用本地 date 命令获取当前日期和时间（不用 python 时间库）。"""
    if os.name == "nt":
        # Windows 下 date 不带参数会进入“输入新的日期”的交互设置，必须加 /t；
        # 时间一并用 time /t 取出
        cmd = ["cmd", "/c", "date /t & time /t"]
    else:
        cmd = ["date"]

    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=15)
    except subprocess.TimeoutExpired:
        return "执行 date 命令超时"
    except OSError as exc:
        return f"执行 date 命令失败: {exc}"

    out = _decode(proc.stdout).strip()
    if proc.returncode == 0 and out:
        return out

    err = _decode(proc.stderr).strip()
    return f"date 命令返回 {proc.returncode}: {err or out or '无输出'}"


def _parse_year(args):
    """从工具入参中取出并校验年份，返回 int 或抛 ValueError。"""
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
        if not year or not (year.lstrip("-").isdigit()):
            raise ValueError(f"year 不是合法整数: {args['year']!r}")
        year = int(year)
    if not isinstance(year, int):
        raise ValueError(f"year 类型不支持: {type(year).__name__}")
    return year


def is_leap_year(args):
    """用 python 代码按格里高利历规则判断闰年。

    能被 4 整除且不能被 100 整除，或能被 400 整除 => 闰年。
    """
    year = _parse_year(args)
    leap = (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)
    return f"{year}年{'是' if leap else '不是'}闰年"


# --------------------------------------------------------------------------- #
# 本地文件操作工具
# --------------------------------------------------------------------------- #
TEXT_SUFFIXES = {
    ".txt", ".text", ".md", ".markdown", ".rst", ".log",
    ".py", ".pyw", ".js", ".mjs", ".ts", ".jsx", ".tsx",
    ".json", ".jsonl", ".xml", ".html", ".htm", ".css", ".scss",
    ".csv", ".tsv", ".ini", ".cfg", ".conf", ".yaml", ".yml", ".toml",
    ".sh", ".bash", ".bat", ".cmd", ".ps1", ".sql", ".properties",
    ".java", ".c", ".h", ".cc", ".cpp", ".hpp", ".cs", ".go", ".rs",
    ".rb", ".php", ".pl", ".lua", ".r", ".tex", ".texinfo",
}

TEXT_FILENAMES = {
    "readme", "license", "licence", "makefile", "dockerfile",
    ".gitignore", ".gitattributes", ".env", ".editorconfig",
}


def _require_arg(args, name):
    """从工具入参中取出必填字段，缺失时抛 ValueError。"""
    if not isinstance(args, dict) or name not in args:
        raise ValueError(f"缺少参数 {name}")
    return args[name]


def _get_path_arg(args, name="path"):
    """把工具入参中的路径转换为绝对 Path，支持 ~ 和相对路径。"""
    raw = _require_arg(args, name)
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"参数 {name} 必须是非空字符串路径")
    return Path(os.path.abspath(os.path.expanduser(raw.strip())))


def _is_text_like(path):
    """根据文件名/扩展名/MIME 判断是否可能是纯文本文件。"""
    if path.name.lower() in TEXT_FILENAMES:
        return True
    suffix = path.suffix.lower()
    if not suffix or suffix in TEXT_SUFFIXES:
        return True
    mime, _ = mimetypes.guess_type(str(path))
    return bool(
        mime
        and (
            mime.startswith("text/")
            or mime
            in {
                "application/json",
                "application/xml",
                "application/javascript",
                "application/x-sh",
            }
        )
    )


def _decode_text(data):
    """按常见编码尝试解码文本，返回 (文本, 实际使用的编码)。"""
    encodings = []
    if data.startswith(b"\xef\xbb\xbf"):
        encodings.append("utf-8-sig")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        encodings.append("utf-16")
    encodings.extend(["utf-8", "gbk", locale.getpreferredencoding(False)])

    tried = set()
    for enc in encodings:
        if not enc or enc in tried:
            continue
        tried.add(enc)
        try:
            return data.decode(enc), enc
        except (UnicodeDecodeError, LookupError):
            continue
    raise ValueError("文件不是可识别的纯文本编码")


def _read_text_file(path):
    """校验并读取纯文本文件，返回 (文本, 编码)。"""
    if not path.exists():
        raise ValueError(f"文件不存在: {path}")
    if not path.is_file():
        raise ValueError(f"不是普通文件: {path}")
    if not _is_text_like(path):
        raise ValueError(f"不支持的文件类型（仅支持纯文本）: {path.suffix or '无扩展名'}")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"读取文件失败: {exc}")
    return _decode_text(data)


def _refuse_critical_path(path, action):
    """拒绝删除/重命名根目录、当前工作目录或用户主目录及其上级。"""
    anchor = Path(path.anchor) if path.anchor else None
    if anchor is not None and path == anchor:
        raise ValueError(f"拒绝{action}根目录: {path}")

    try:
        target = path.resolve()
    except OSError:
        target = path.absolute()

    for base, label in ((Path.cwd(), "当前工作目录"), (Path.home(), "用户主目录")):
        try:
            base = base.resolve()
        except OSError:
            continue
        if target == base or target in base.parents:
            raise ValueError(f"拒绝{action}{label}或其上级目录: {path}")


def get_current_directory(args=None):
    """获取当前进程的工作目录。"""
    return os.getcwd()


def list_directory(args):
    """列出目录下的所有文件和子目录。"""
    path = _get_path_arg(args)
    if not path.exists():
        raise ValueError(f"目录不存在: {path}")
    if not path.is_dir():
        raise ValueError(f"不是目录: {path}")

    try:
        entries = sorted(
            path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())
        )
    except OSError as exc:
        raise ValueError(f"读取目录失败: {exc}")

    lines = [f"目录: {path}", f"共 {len(entries)} 项"]
    for entry in entries:
        try:
            if entry.is_dir():
                kind = "目录"
            elif entry.is_file():
                kind = f"文件, {entry.stat().st_size} 字节"
            else:
                kind = "其他"
        except OSError:
            kind = "未知"
        lines.append(f"[{kind}] {entry.name}")
    return "\n".join(lines)


def get_file_type(args):
    """获取文件或目录的类型信息。"""
    path = _get_path_arg(args)
    if not path.exists():
        raise ValueError(f"路径不存在: {path}")

    if path.is_dir():
        kind = "目录"
    elif path.is_file():
        kind = "普通文件"
    else:
        kind = "其他（设备/管道等）"

    suffix = path.suffix.lower() or "无"
    mime, _ = mimetypes.guess_type(str(path))
    lines = [
        f"路径: {path}",
        f"类型: {kind}",
        f"扩展名: {suffix}",
        f"MIME 类型: {mime or '未知'}",
    ]
    if path.is_file():
        lines.append(f"纯文本: {'是' if _is_text_like(path) else '否'}")
    if path.is_symlink():
        lines.append("符号链接: 是")
    return "\n".join(lines)


def read_text_file(args):
    """读取纯文本文件的完整内容。"""
    path = _get_path_arg(args)
    text, encoding = _read_text_file(path)
    return f"文件: {path}\n编码: {encoding}\n内容:\n{text}"


def create_file(args):
    """在指定目录下创建新文件（不覆盖已有文件）。"""
    directory = _get_path_arg(args, "directory")
    filename = _require_arg(args, "filename")
    if not isinstance(filename, str) or not filename.strip():
        raise ValueError("参数 filename 必须是非空字符串")
    filename = filename.strip()
    if Path(filename).name != filename or filename in (".", ".."):
        raise ValueError("filename 只能是文件名，不能包含路径分隔符")

    if not directory.exists():
        raise ValueError(f"目录不存在: {directory}")
    if not directory.is_dir():
        raise ValueError(f"不是目录: {directory}")

    path = directory / filename
    if path.exists():
        raise ValueError(f"文件已存在，不会覆盖: {path}")

    content = args.get("content", "")
    if content is None:
        content = ""
    if not isinstance(content, str):
        raise ValueError("参数 content 必须是字符串")

    try:
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"创建文件失败: {exc}")
    return f"已创建文件: {path}\n写入 {len(content)} 个字符"


def edit_file(args):
    """编辑纯文本文件：覆盖、追加或替换指定文本。"""
    path = _get_path_arg(args)
    text, encoding = _read_text_file(path)

    mode = str(args.get("mode", "overwrite")).strip().lower()
    if mode not in ("overwrite", "append", "replace"):
        raise ValueError("mode 必须是 overwrite、append 或 replace")

    content = args.get("content", "")
    if content is None:
        content = ""
    if not isinstance(content, str):
        raise ValueError("参数 content 必须是字符串")

    if mode == "overwrite":
        new_text = content
        summary = f"已覆盖文件: {path}\n写入 {len(content)} 个字符"
    elif mode == "append":
        new_text = text + content
        summary = f"已追加到文件: {path}\n追加 {len(content)} 个字符"
    else:
        old_text = args.get("old_text")
        if not isinstance(old_text, str) or not old_text:
            raise ValueError("replace 模式需要提供非空 old_text")
        count = text.count(old_text)
        if count == 0:
            raise ValueError("文件中未找到 old_text，未做修改")
        new_text = text.replace(old_text, content)
        summary = f"已替换文件: {path}\n替换 {count} 处，写入 {len(content)} 个字符"

    try:
        data = new_text.encode(encoding)
    except (UnicodeEncodeError, LookupError) as exc:
        raise ValueError(f"内容无法按原编码 {encoding} 保存: {exc}")
    try:
        path.write_bytes(data)
    except OSError as exc:
        raise ValueError(f"写入文件失败: {exc}")
    return summary


def create_directory(args):
    """创建新目录（自动创建上级目录）。"""
    path = _get_path_arg(args)
    if path.exists():
        raise ValueError(f"目标已存在: {path}")
    try:
        path.mkdir(parents=True)
    except OSError as exc:
        raise ValueError(f"创建目录失败: {exc}")
    return f"已创建目录: {path}"


def delete_directory(args):
    """删除目录及其全部内容（支持非空目录）。"""
    path = _get_path_arg(args)
    if not path.exists():
        raise ValueError(f"目录不存在: {path}")
    if path.is_symlink():
        raise ValueError("目标是符号链接，请使用 deleteFile 删除链接本身")
    if not path.is_dir():
        raise ValueError(f"不是目录: {path}")

    _refuse_critical_path(path, "删除")
    try:
        shutil.rmtree(path)
    except OSError as exc:
        raise ValueError(f"删除目录失败: {exc}")
    return f"已删除目录: {path}"


def delete_file(args):
    """删除指定文件。"""
    path = _get_path_arg(args)
    if not path.exists():
        raise ValueError(f"文件不存在: {path}")
    if path.is_dir() and not path.is_symlink():
        raise ValueError(f"目标是目录，请使用 deleteDirectory: {path}")
    try:
        path.unlink()
    except OSError as exc:
        raise ValueError(f"删除文件失败: {exc}")
    return f"已删除文件: {path}"


def rename_file_or_directory(args):
    """重命名文件或目录；new_path 只给名称时在原目录内重命名。"""
    old_path = _get_path_arg(args, "old_path")
    if not old_path.exists():
        raise ValueError(f"原路径不存在: {old_path}")

    new_raw = _require_arg(args, "new_path")
    if not isinstance(new_raw, str) or not new_raw.strip():
        raise ValueError("参数 new_path 必须是非空字符串")
    new_raw = new_raw.strip()

    new_path = Path(os.path.expanduser(new_raw))
    if not new_path.is_absolute():
        if new_path.parent == Path("."):
            new_path = old_path.parent / new_path.name
        else:
            new_path = Path(os.path.abspath(new_raw))

    if new_path.exists():
        raise ValueError(f"目标已存在，不会覆盖: {new_path}")
    if not new_path.parent.exists():
        raise ValueError(f"目标目录不存在: {new_path.parent}")

    _refuse_critical_path(old_path, "重命名")
    try:
        old_path.rename(new_path)
    except OSError as exc:
        raise ValueError(f"重命名失败: {exc}")
    return f"已重命名:\n{old_path}\n-> {new_path}"


TOOL_HANDLERS = {
    "getDate": get_date,
    "isLeapYear": is_leap_year,
    "getCurrentDirectory": get_current_directory,
    "listDirectory": list_directory,
    "getFileType": get_file_type,
    "readTextFile": read_text_file,
    "createFile": create_file,
    "editFile": edit_file,
    "createDirectory": create_directory,
    "deleteDirectory": delete_directory,
    "deleteFile": delete_file,
    "renameFileOrDirectory": rename_file_or_directory,
}


def dispatch_tool(call):
    """按 tool_call 分发到本地实现，返回给模型的工具结果字符串。"""
    fn = call.get("function") or {}
    name = fn.get("name", "")
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        return f"未知工具: {name}"

    raw_args = fn.get("arguments") or "{}"
    try:
        args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        if not isinstance(args, dict):
            raise ValueError("arguments 必须是 JSON 对象")
    except ValueError as exc:
        return f"工具 {name} 入参解析失败: {exc}"

    try:
        return handler(args)
    except Exception as exc:  # 工具异常不能让整个会话崩溃
        return f"工具 {name} 执行异常: {exc}"


# --------------------------------------------------------------------------- #
# 配置与请求
# --------------------------------------------------------------------------- #
def load_config(path=None):
    """读取脚本同目录 config.ini 的 [llm] 配置，缺失时用默认值。"""
    cfg = configparser.ConfigParser()
    # utf-8-sig 兼容 Windows 记事本/VSCode 保存的带 BOM 文件
    cfg.read(str(path or SCRIPT_DIR / "config.ini"), encoding="utf-8-sig")

    llm = dict(cfg["llm"]) if cfg.has_section("llm") else {}

    base_url = llm.get("base_url", "http://localhost:11434/v1").strip().rstrip("/")
    model_name = llm.get("model_name", "qwen2.5").strip()
    api_key = llm.get("api_key", "").strip()
    try:
        temperature = float(llm.get("temperature", "0.7"))
    except ValueError:
        temperature = 0.7

    if not api_key:
        print("[提示] 未配置 api_key，将尝试无鉴权访问（本地服务可忽略）")

    return {
        "base_url": base_url,
        "model_name": model_name,
        "api_key": api_key,
        "temperature": temperature,
    }


def _merge_tool_call(bucket, piece):
    """把流式 delta 中的 tool_calls 片段按 index 合并成完整调用。"""
    index = piece.get("index", 0)
    slot = bucket.setdefault(
        index,
        {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
    )
    if piece.get("id"):
        slot["id"] = piece["id"]
    if piece.get("type"):
        slot["type"] = piece["type"]
    fn = piece.get("function") or {}
    # name 一般只出现一次，arguments 会分片下发，需拼接
    if fn.get("name"):
        slot["function"]["name"] = fn["name"]
    if fn.get("arguments"):
        slot["function"]["arguments"] += fn["arguments"]


def _parse_message(message, parts, bucket):
    """从 assistant message 中提取正文与 tool_calls（流式/非流式通用）。"""
    content = message.get("content")
    if content:
        parts.append(content)
        sys.stdout.write(content)
        sys.stdout.flush()
    for piece in message.get("tool_calls") or []:
        if isinstance(piece, dict):
            _merge_tool_call(bucket, piece)


def chat_once(cfg, messages):
    """流式调用 {base_url}/chat/completions：逐字打印，返回结果字典。

    返回 {"ok": bool, "content": str|None, "tool_calls": list}。
    传输/解析失败时 ok=False（不中断主循环）。
    """
    url = f"{cfg['base_url']}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if cfg["api_key"]:
        headers["Authorization"] = f"Bearer {cfg['api_key']}"

    payload = {
        "model": cfg["model_name"],
        "messages": messages,
        "temperature": cfg["temperature"],
        "stream": True,
        # 注册 function call 工具，由模型自行决定调用哪个
        "tools": TOOLS,
        "tool_choice": "auto",
    }

    def failed():
        return {"ok": False, "content": None, "tool_calls": []}

    try:
        # stream=True 让 requests 收到响应头就返回，边收边打印（否则会整包缓冲）
        # 超时按「连上后多久没数据」算，给足 120s
        resp = requests.post(
            url, json=payload, headers=headers, timeout=(10, 120), stream=True
        )
    except requests.RequestException:
        print("请检查 base_url 与网络连接")
        return failed()

    if resp.status_code != 200:
        # 多数服务在响应头就带回了错误原因
        detail = ""
        try:
            detail = resp.json().get("error", {}).get("message", "")
        except (AttributeError, ValueError):
            pass
        if resp.status_code == 401:
            print("API Key 无效")
        elif resp.status_code == 404:
            print("模型不存在，请检查 model_name")
        elif resp.status_code == 429 or resp.status_code >= 500:
            print("服务限流或不可用，请稍后重试")
        else:
            print(f"请求失败（HTTP {resp.status_code}）：{detail or '请检查 base_url 与网络连接'}")
        resp.close()
        return failed()

    parts = []
    raw_lines = []
    bucket = {}
    saw_sse = False
    try:
        resp.encoding = resp.encoding or "utf-8"
        # SSE 逐行解析：data: {json}，以 data: [DONE] 结束
        for line in resp.iter_lines():
            if not line.startswith(b"data:"):
                raw_lines.append(line)  # 注释行/心跳，或服务未按 SSE 返回
                continue
            saw_sse = True
            data = line[5:].strip()
            if data == b"[DONE]":
                break
            try:
                choice = json.loads(data)["choices"][0]
            except (ValueError, KeyError, IndexError):
                continue  # 空行/心跳等非内容行，忽略
            delta = choice.get("delta") or {}
            if delta.get("content"):
                parts.append(delta["content"])
                sys.stdout.write(delta["content"])
                sys.stdout.flush()
            if delta.get("tool_calls"):
                for piece in delta["tool_calls"]:
                    if isinstance(piece, dict):
                        _merge_tool_call(bucket, piece)

        # 兼容：服务忽略 stream 参数时会直接返回普通 JSON
        if not saw_sse and raw_lines:
            message = json.loads(
                b"\n".join(raw_lines).decode("utf-8", errors="replace")
            )["choices"][0]["message"]
            _parse_message(message, parts, bucket)
    except requests.RequestException:
        print("\n连接中断，请检查 base_url 与网络连接")
        return failed()
    except (ValueError, KeyError, IndexError, TypeError):
        print("\n响应格式异常，无法解析")
        return failed()
    finally:
        resp.close()

    tool_calls = [bucket[i] for i in sorted(bucket)]
    return {
        "ok": True,
        "content": "".join(parts),
        "tool_calls": tool_calls,
    }


def run_turn(cfg, messages):
    """处理一轮用户提问：模型若发起工具调用，则执行工具并把结果回传继续追问。"""
    for _ in range(MAX_TOOL_ROUNDS):
        result = chat_once(cfg, messages)
        if not result["ok"]:
            return False

        content = result["content"]
        tool_calls = result["tool_calls"]

        assistant_msg = {"role": "assistant", "content": content or None}

        if tool_calls:
            assistant_msg["tool_calls"] = tool_calls
            messages.append(assistant_msg)
            if content:
                print()  # 正文已流式打印，补换行

            for call in tool_calls:
                name = (call.get("function") or {}).get("name", "?")
                print(f"[工具调用] {name} ...")
                output = dispatch_tool(call)
                print(f"[工具返回]\n{output}\n")
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id", ""),
                        "content": output,
                    }
                )
            continue  # 带着工具结果重新请求模型

        # 普通回答：正文在流式过程中已逐字打印
        messages.append(assistant_msg)
        if content:
            print()  # 补个换行
        return True

    print("工具调用轮次过多，本轮已停止")
    return False


def main():
    # 避免 Windows 控制台/重定向时输出中文编码报错
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    cfg = load_config()
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    print("输入问题开始对话（流式输出，支持日期/闰年/本地文件操作工具，/help 帮助，/quit 退出）")

    while True:
        try:
            user_input = input("你: ").strip()
        except EOFError:  # 输入流结束
            print("再见")
            break

        if not user_input:
            continue

        if user_input.startswith("/"):
            cmd = user_input.lower()
            if cmd in ("/quit", "/exit"):
                print("再见")
                break
            elif cmd == "/help":
                print("命令: /quit /exit 退出, /clear 清空历史, /help 帮助")
                print("工具: getDate 获取当前日期时间, isLeapYear 判断闰年")
                print(
                    "文件工具: getCurrentDirectory 当前目录, listDirectory 列出目录, "
                    "getFileType 文件类型, readTextFile 读取文本, "
                    "createFile 创建文件, editFile 编辑文本, "
                    "createDirectory 创建目录, deleteDirectory 删除目录, "
                    "deleteFile 删除文件, renameFileOrDirectory 重命名"
                )
            elif cmd == "/clear":
                messages = [{"role": "system", "content": SYSTEM_PROMPT}]
                print("已清空历史")
            else:
                print("未知命令，输入 /help 查看")
            continue

        messages.append({"role": "user", "content": user_input})

        # 先存一份历史快照：本轮失败时回滚，避免留下半截 tool 消息
        snapshot = list(messages)
        if not run_turn(cfg, messages):
            messages[:] = snapshot


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:  # 任意时刻 Ctrl+C 强行退出
        print("\n再见")
