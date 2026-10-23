# -*- coding: utf-8 -*-
"""本地文件操作工具。

所有路径参数都会展开 ~ 并转为绝对路径；破坏性操作带有根目录 /
主目录保护。handler 抛出的异常由 ToolRegistry 统一转成工具错误。
"""
from __future__ import annotations

import locale
import mimetypes
import os
import shutil
from pathlib import Path
from typing import Any

from .registry import Tool

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


def _require_arg(args: dict[str, Any], name: str) -> Any:
    if not isinstance(args, dict) or name not in args:
        raise ValueError(f"缺少参数 {name}")
    return args[name]


def _get_path_arg(args: dict[str, Any], name: str = "path") -> Path:
    raw = _require_arg(args, name)
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"参数 {name} 必须是非空字符串路径")
    return Path(os.path.abspath(os.path.expanduser(raw.strip())))


def _is_text_like(path: Path) -> bool:
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


def _decode_text(data: bytes) -> tuple[str, str]:
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


def _read_text_file(path: Path) -> tuple[str, str]:
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


def _refuse_critical_path(path: Path, action: str) -> None:
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


def list_directory(args: dict[str, Any]) -> str:
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


def get_file_type(args: dict[str, Any]) -> str:
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


def read_text_file(args: dict[str, Any]) -> str:
    path = _get_path_arg(args)
    text, encoding = _read_text_file(path)
    return f"文件: {path}\n编码: {encoding}\n内容:\n{text}"


def create_file(args: dict[str, Any]) -> str:
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


def edit_file(args: dict[str, Any]) -> str:
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


def create_directory(args: dict[str, Any]) -> str:
    path = _get_path_arg(args)
    if path.exists():
        raise ValueError(f"目标已存在: {path}")
    try:
        path.mkdir(parents=True)
    except OSError as exc:
        raise ValueError(f"创建目录失败: {exc}")
    return f"已创建目录: {path}"


def delete_directory(args: dict[str, Any]) -> str:
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


def delete_file(args: dict[str, Any]) -> str:
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


def rename_file_or_directory(args: dict[str, Any]) -> str:
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


def build_filesystem_tools() -> list[Tool]:
    return [
        Tool(
            name="listDirectory",
            description="列出指定目录下的所有文件和子目录，包含名称、类型和文件大小",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "要列出的目录路径，支持相对路径或绝对路径",
                    }
                },
                "required": ["path"],
            },
            handler=list_directory,
        ),
        Tool(
            name="getFileType",
            description="获取指定文件（或目录）的类型，包括扩展名、MIME 类型以及是否为纯文本",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "要查询的文件或目录路径",
                    }
                },
                "required": ["path"],
            },
            handler=get_file_type,
        ),
        Tool(
            name="readTextFile",
            description="读取指定纯文本文件的完整内容，仅支持文本类文件（如 .txt/.md/.py/.json 等）",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "要读取的纯文本文件路径",
                    }
                },
                "required": ["path"],
            },
            handler=read_text_file,
        ),
        Tool(
            name="createFile",
            description="在指定目录下按文件名创建新文件，文件已存在时不会覆盖，可选写入初始文本内容",
            parameters={
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
            handler=create_file,
        ),
        Tool(
            name="editFile",
            description=(
                "编辑指定纯文本文件的内容。mode=overwrite 用 content 覆盖整个文件；"
                "mode=append 把 content 追加到文件末尾；mode=replace 把文件中的 old_text 替换为 content"
            ),
            parameters={
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
            handler=edit_file,
        ),
        Tool(
            name="createDirectory",
            description="创建新目录，会自动创建缺失的上级目录；目标已存在时返回错误",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "要创建的目录路径",
                    }
                },
                "required": ["path"],
            },
            handler=create_directory,
        ),
        Tool(
            name="deleteDirectory",
            description="删除指定目录及其中的所有内容（支持非空目录），请谨慎使用",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "要删除的目录路径",
                    }
                },
                "required": ["path"],
            },
            handler=delete_directory,
        ),
        Tool(
            name="deleteFile",
            description="删除指定文件（不能用于删除目录），请谨慎使用",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "要删除的文件路径",
                    }
                },
                "required": ["path"],
            },
            handler=delete_file,
        ),
        Tool(
            name="renameFileOrDirectory",
            description="重命名文件或目录。new_path 只写名称时在同一目录内重命名，也可给出新的完整路径（目标不能已存在）",
            parameters={
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
            handler=rename_file_or_directory,
        ),
    ]
