# -*- coding: utf-8 -*-
"""chat2.py: 终端 AI 问答 Agent（OpenAI 兼容接口 + function call）

基于 chat.py，保留 getDate（调用本地 date 命令），并新增 function call 工具 isLeapYear：
    由 python 代码计算输入年份是否为闰年（格里高利历规则）。

用法: python chat2.py
"""
import configparser
import json
import locale
import os
import subprocess
import sys
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent

# 内置中文指令，要求模型按固定格式回复（首行 ---、正文、尾行 ---）
SYSTEM_PROMPT = (
    "你是一个乐于助人的AI助手。请严格按以下格式回复：\n"
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


TOOL_HANDLERS = {
    "getDate": get_date,
    "isLeapYear": is_leap_year,
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

    print("输入问题开始对话（流式输出，支持 getDate / isLeapYear 工具，/help 帮助，/quit 退出）")

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
