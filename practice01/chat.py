# -*- coding: utf-8 -*-
"""chat.py: 终端 AI 问答 Agent（OpenAI 兼容接口）

用法: python chat.py
"""
import configparser
import json
import sys

import requests

# 内置中文指令，要求模型按固定格式回复（首行 ---、正文、尾行 ---）
SYSTEM_PROMPT = (
    "你是一个乐于助人的AI助手。请严格按以下格式回复：\n"
    "第一行只输出 ---\n"
    "随后输出对问题的回答正文（可多行）\n"
    "最后一行再只输出 ---"
)


def load_config(path="config.ini"):
    """读取同目录 config.ini 的 [llm] 配置，缺失时用默认值。"""
    cfg = configparser.ConfigParser()
    # utf-8-sig 兼容 Windows 记事本/VSCode 保存的带 BOM 文件
    cfg.read(path, encoding="utf-8-sig")

    llm = dict(cfg["llm"]) if cfg.has_section("llm") else {}

    base_url = llm.get("base_url", "http://localhost:11434/v1").strip().rstrip("/")
    model_name = llm.get("model_name", "qwen2.5").strip()
    api_key = llm.get("api_key", "").strip()
    try:
        temperature = float(llm.get("temperature", "0.7"))
    except ValueError:
        temperature = 0.7
    try:
        max_history = int(llm.get("max_history", "10"))
    except ValueError:
        max_history = 10

    if not api_key:
        print("[提示] 未配置 api_key，将尝试无鉴权访问（本地服务可忽略）")

    return {
        "base_url": base_url,
        "model_name": model_name,
        "api_key": api_key,
        "temperature": temperature,
        "max_history": max(1, max_history),
    }


def chat_once(cfg, messages):
    """流式调用 {base_url}/chat/completions：逐字打印，边收边攒完整回答。

    出错时打印提示并返回 None（不中断主循环）。
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
    }

    try:
        # 流式下超时按「连上后多久没数据」算，给足 120s
        resp = requests.post(url, json=payload, headers=headers, timeout=(10, 120))
    except requests.RequestException:
        print("请检查 base_url 与网络连接")
        return None

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
        return None

    parts = []
    try:
        # SSE 逐行解析：data: {json}，以 data: [DONE] 结束
        for line in resp.iter_lines():
            if not line.startswith(b"data:"):
                continue
            data = line[5:].strip()
            if data == b"[DONE]":
                break
            try:
                delta = json.loads(data)["choices"][0]["delta"].get("content")
            except (ValueError, KeyError, IndexError):
                continue  # 空行/心跳等非内容行，忽略
            if delta:
                parts.append(delta)
                sys.stdout.write(delta)
                sys.stdout.flush()
    except requests.RequestException:
        print("\n连接中断，请检查 base_url 与网络连接")
        return None
    finally:
        resp.close()

    return "".join(parts)


def main():
    # 避免 Windows 控制台/重定向时输出中文编码报错
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    cfg = load_config()
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    max_rounds = cfg["max_history"]

    print(f"输入问题开始对话（流式输出，保留最近 {max_rounds} 轮，/help 帮助，/quit 退出）")

    while True:
        try:
            user_input = input("你: ").strip()
        except (EOFError, KeyboardInterrupt):  # Ctrl+C 或输入流结束
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
            elif cmd == "/clear":
                messages = [{"role": "system", "content": SYSTEM_PROMPT}]
                print("已清空历史")
            else:
                print("未知命令，输入 /help 查看")
            continue

        messages.append({"role": "user", "content": user_input})
        # 只保留最近 max_rounds 轮（含本轮提问），超出丢弃最旧的
        # 消息为 system + user/assistant 交替，本轮提问占掉 1 条
        cutoff = 2 * max_rounds - 1
        if len(messages) - 1 > cutoff:
            messages = [messages[0]] + messages[-cutoff:]

        try:
            answer = chat_once(cfg, messages)
        except KeyboardInterrupt:  # 流式输出中按 Ctrl+C，丢弃本轮
            print()
            answer = None

        if not answer:
            messages.pop()  # 本轮失败或无输出，移除该问题，不污染历史
            continue

        print()  # 流式已逐字打印，这里补个换行
        messages.append({"role": "assistant", "content": answer})


if __name__ == "__main__":
    main()