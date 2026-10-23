# practice02 · 终端 AI 问答 Agent（OpenAI 兼容接口 + function call）

一个跑在终端里的命令行 AI 助手。在 `practice01` 的流式问答基础上，新增 **function call（工具调用）**
能力：模型可以自己决定调用本地 `getDate` 工具，通过执行系统 `date` 命令拿到电脑当前的日期与时间，
再把结果交回模型继续回答。

- 纯命令行交互，流式逐字输出
- 只需一个 OpenAI 兼容接口（DeepSeek 云端 / 本地 Ollama 均可）
- 代码架构图：[`chat_architecture.mmd`](./chat_architecture.mmd)（Mermaid 格式，纯文本）

## 目录

- [功能特性](#功能特性)
- [文件说明](#文件说明)
- [环境依赖](#环境依赖)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [交互命令](#交互命令)
- [运行流程](#运行流程)
- [代码架构](#代码架构)
- [关键实现细节](#关键实现细节)
- [如何新增一个工具](#如何新增一个工具)
- [常见问题](#常见问题)

## 功能特性

| 能力 | 说明 |
| --- | --- |
| 流式输出 | `stream=True` + SSE 逐行解析，`delta.content` 边收边打印，不整包缓冲 |
| 工具调用 | 声明 `getDate` 工具，`tool_choice=auto` 让模型自行决定是否调用；单轮最多 8 次工具往返 |
| 多轮记忆 | `messages` 维护完整对话历史，`/clear` 可随时重置 |
| 回复格式约束 | `SYSTEM_PROMPT` 要求模型首行与尾行都只输出 `---`，正文在中间 |
| 错误兜底 | 401 / 404 / 429 / 5xx / 超时 / 网络异常 / 响应格式异常各有明确提示，不崩溃退出 |
| 失败回滚 | 本轮请求失败时回滚历史快照，避免留下半截 `assistant` / `tool` 消息污染后续上下文 |
| 编码兼容 | 启动时 `stdout.reconfigure(utf-8)`；子进程输出按 utf-8 → 系统首选编码 → gbk 依次尝试解码 |
| 配置外置 | 接口地址、模型、Key、温度全部放在 `config.ini`，不进版本库 |

## 文件说明

| 文件 | 说明 |
| --- | --- |
| `chat.py` | 主程序（本 README 与架构图对应的代码） |
| `chat_architecture.mmd` | 代码架构图，Mermaid 格式纯文本 |
| `config.ini` | 本地配置，含真实 API Key，已被 `.gitignore` 忽略 |
| `config.example.ini` | 配置模板，复制为 `config.ini` 后填写自己的 Key |
| `.gitignore` | 忽略 `config.ini`、`__pycache__/`、`*.py[cod]`、虚拟环境目录 |
| `chat2.py` / `chat3.py` | 同目录下的后续练习版本（逐步扩展的迭代代码） |

## 环境依赖

- Python 3.7+（用到 `sys.stdout.reconfigure`）
- 第三方库：`requests`

```bash
pip install requests
```

## 快速开始

1. 复制配置模板并填入自己的 API Key：

   ```bash
   cp config.example.ini config.ini      # Windows: copy config.example.ini config.ini
   ```

2. 编辑 `config.ini` 的 `[llm]` 节，至少确认 `base_url`、`model_name`、`api_key`。

3. 运行：

   ```bash
   python chat.py
   ```

4. 试一句会触发工具调用的问题，例如：

   ```text
   你: 现在几点了？
   ```

   程序会打印 `[工具调用] getDate ...`、`[工具返回] ...`，然后给出最终回答。

## 配置说明

`chat.py` 只读取脚本同目录下的 `config.ini`，`[llm]` 节缺失或字段缺失时使用默认值：

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `base_url` | `http://localhost:11434/v1` | OpenAI 兼容接口地址，需以 `/v1` 结尾；自动去掉末尾多余斜杠 |
| `model_name` | `qwen2.5` | 模型名称 |
| `api_key` | 空 | 为空时只打印提示，按无鉴权方式请求（本地服务可留空） |
| `temperature` | `0.7` | 采样温度，非法值自动回退为 0.7 |

常用 `base_url` 参考：

- DeepSeek 云端：`https://api.deepseek.com/v1`
- 本地 Ollama：`http://localhost:11434/v1`（`api_key` 可留空或随便填）

## 交互命令

| 命令 | 作用 |
| --- | --- |
| 直接输入文本 | 作为用户提问发送给模型 |
| `/help` | 显示可用命令与工具说明 |
| `/clear` | 清空对话历史，只保留 system 消息 |
| `/quit`、`/exit` | 退出程序 |
| `Ctrl+C` | 任意时刻强制退出（打印「再见」） |
| `Ctrl+D` / EOF | 输入流结束，正常退出 |

## 运行流程

1. `main()` 把 `stdout` 重设为 UTF-8，避免 Windows 控制台或重定向时中文报错。
2. `load_config()` 读取 `config.ini`，做类型转换与默认值兜底。
3. 初始化 `messages = [{role: system, content: SYSTEM_PROMPT}]`。
4. 循环读取用户输入：以 `/` 开头走内置命令分支，否则追加 `user` 消息并保存历史快照。
5. `run_turn()` 进入「请求—工具—再请求」循环（最多 `MAX_TOOL_ROUNDS = 8` 轮）：
   - `chat_once()` 流式请求模型，边打印正文边收集 `content` 与 `tool_calls`；
   - 若模型返回 `tool_calls`，则追加 `assistant` 消息（含 `tool_calls`），逐个 `dispatch_tool()` 执行，
     把结果作为 `role: tool` 消息追加回历史，然后带着工具结果重新请求模型；
   - 若没有工具调用，追加 `assistant` 消息并结束本轮。
6. 本轮失败（网络/解析错误、工具轮次超限）时，用快照回滚 `messages`，回到「只保留用户提问」的状态。

## 代码架构

完整架构图见 [`chat_architecture.mmd`](./chat_architecture.mmd)，分六层：

| 层 | 主要函数 / 对象 | 职责 |
| --- | --- | --- |
| ① 启动与初始化 | `__main__` 保护块、`main()`、`load_config()` | 设置输出编码、读配置、构造 `messages`、异常收口 |
| ② 交互主循环 | `main()` 内 `while True` | 读取输入、分派内置命令、保存历史快照、失败回滚 |
| ③ 单轮对话 | `run_turn()` | 驱动「模型请求 → 工具执行 → 再请求」的多轮工具循环 |
| ④ 模型请求 | `chat_once()`、`_merge_tool_call()`、`_parse_message()` | 组装请求、SSE 流式解析与打印、合并工具调用分片、错误分类 |
| ⑤ 工具层 | `TOOLS`、`TOOL_HANDLERS`、`dispatch_tool()`、`get_date()`、`_decode()` | 工具声明与分发、执行本地 `date` 命令、输出解码 |
| ⑥ 常量与配置 | `SYSTEM_PROMPT`、`MAX_TOOL_ROUNDS`、`config.example.ini` | 回复格式约束、工具轮次上限、配置模板 |

渲染方式：

- VS Code：安装 Markdown Preview Mermaid Support（或 Mermaid 插件），打开 `.mmd` 预览；
- 在线：把文件内容粘到 <https://mermaid.live> 即可查看与导出图片；
- 命令行：可用 `mmdc -i chat_architecture.mmd -o chat_architecture.png` 离线导出。

## 关键实现细节

### 1. 为什么必须流式

`requests.post(..., stream=True)` 让客户端收到响应头就返回，随后 `resp.iter_lines()` 逐行读 SSE，
`delta.content` 一到就 `stdout.write` 并 `flush`，用户能看到逐字输出。若不流式，长回答要等整包返回。

### 2. tool_calls 分片合并

流式响应中 `tool_calls` 会按 `index` 分片下发，函数名只出现一次，`arguments` 会被切成多段。
`_merge_tool_call()` 以 `index` 为键维护 `bucket`，名称只记录一次、`arguments` 累加拼接，
最后按 `index` 排序还原成完整调用列表。

### 3. Windows 下不能直接调 `date`

Windows 的 `date` 不带参数会进入「输入新的日期」交互模式并卡住进程，因此：

- Windows 使用 `cmd /c "date /t & time /t"`；
- 其他平台使用 `date`；
- `subprocess.run(capture_output=True, timeout=15)`，超时与 `OSError` 都转成文本返回。

### 4. 子进程输出解码

Windows 的 `date` / `time` 按 OEM/ANSI 代码页输出，直接按 UTF-8 解码会报错。
`_decode()` 依次尝试 `utf-8`、`locale.getpreferredencoding(False)`、`gbk`，
全部失败时用 UTF-8 + `errors="replace"` 兜底，保证不会因编码问题中断。

### 5. 错误不抛出，转成返回值

- `dispatch_tool()` 遇到未知工具或工具异常，都返回字符串说明，会话继续；
- `chat_once()` 传输/解析失败返回 `{"ok": False, ...}`，由 `run_turn()` 转成 `False`；
- `main()` 依据 `run_turn()` 的返回值决定是否回滚历史快照。

### 6. 兼容不按 SSE 返回的服务

部分服务会忽略 `stream` 参数直接返回普通 JSON。代码在未解析到任何 `data:` 行时，
把原始行拼回整体 JSON，交给 `_parse_message()` 走非流式路径解析，避免误判为失败。

## 如何新增一个工具

三步即可：

1. **声明**：在 `TOOLS` 中追加一个 `{"type": "function", "function": {"name": ..., "description": ..., "parameters": {...}}}`
   结构，`parameters` 用 JSON Schema 描述入参。
2. **实现**：写一个无参或按需接收参数的函数，返回字符串（字符串会作为工具结果回传给模型）。
3. **注册**：把 `工具名: 函数` 加进 `TOOL_HANDLERS`；如需传参，在 `dispatch_tool()` 里解析
   `call["function"]["arguments"]`（注意它是 JSON 字符串）后传给对应函数。

## 常见问题

**Q：提示「请检查 base_url 与网络连接」？**
A：检查 `config.ini` 的 `base_url` 是否可达、是否以 `/v1` 结尾；本地服务需确认已启动。

**Q：提示「API Key 无效」（HTTP 401）？**
A：`api_key` 填错或过期；本地 Ollama 可以留空。

**Q：提示「模型不存在」（HTTP 404）？**
A：`model_name` 与服务端实际可用模型不一致。

**Q：中文输出乱码 / 报 UnicodeEncodeError？**
A：程序启动已执行 `stdout.reconfigure(encoding="utf-8", errors="replace")`；
若仍乱码，可把控制台代码页切到 UTF-8（`chcp 65001`）。

**Q：模型一直反复调用工具？**
A：单轮最多 8 次工具往返，超出会打印「工具调用轮次过多，本轮已停止」并回滚本轮历史。

**Q：`config.ini` 会被提交吗？**
A：不会，`.gitignore` 已忽略 `config.ini`；请只提交 `config.example.ini`。
