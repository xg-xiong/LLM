# xAgent · 可插拔界面的终端 AI Agent

基于 `agent/practice02/chat3.py` 重构：保留原有流式对话、function call 与全部本地文件工具，
同时把**业务核心**与**界面**彻底分离。当前提供 Textual TUI，后续增加 Web / Desktop
界面时无需改动 core。

## 特性

- **core / tui 分层**：core 不依赖 Textual、不写 stdout，可被任意 UI 复用
- **事件驱动**：core 通过 `AgentEvent` 广播流式正文、工具调用、错误与回合结束
- **可取消**：`CancellationToken` 可中断流式 HTTP 读取和工具循环
- **可回滚**：一轮失败或取消时丢弃半截 `assistant` / `tool` 消息
- **工具模块化**：工具 = Schema + handler，注册后即可被模型调用
- **网页正文提取**：`fetchWeb` 调用本地 `curl` 下载 HTML，再用 `trafilatura` 转为 Markdown
- **网络搜索**：`searchWeb` 调用百度千帆搜索 API，返回实时摘要、标题与参考 URL
- **本地 CLI 调用**：`Runcli` 使用 `subprocess` 和 `shell=False` 执行本机命令行程序
- **可扩展**：配置、LLM 客户端、工具、界面均为可替换的独立模块

## 目录结构

```text
xAgent/
├── core/                     # 业务核心（无 UI 依赖）
│   ├── agent.py              # Agent 编排：对话、工具循环、事件、回滚
│   ├── config.py             # config.ini + 环境变量解析
│   ├── conversation.py       # 对话历史 / 快照 / 回滚
│   ├── events.py             # UI 无关事件契约
│   ├── models.py             # ChatResult / ToolResult / TurnResult
│   ├── cancellation.py       # 线程安全取消令牌
│   ├── prompts.py            # 系统提示词与轮次上限
│   ├── llm/
│   │   ├── base.py           # ChatClient 端口（Protocol）
│   │   └── openai_compat.py  # OpenAI 兼容流式客户端（requests）
│   └── tools/
│       ├── registry.py       # Tool / ToolRegistry / 参数解析
│       ├── system.py         # 日期、闰年、当前目录、本地 CLI（Runcli）
│       ├── filesystem.py     # 目录与文本文件操作
│       ├── web.py            # curl 抓取网页 + trafilatura 提取 Markdown 正文
│       └── search.py         # 百度千帆搜索 API（searchWeb）
├── tui/                      # Textual 适配层
│   ├── app.py                # App、事件桥接、命令、工作线程
│   ├── widgets.py            # 对话区控件
│   └── styles.tcss           # 样式
├── main.py                   # 统一启动入口
├── config.example.ini
├── pyproject.toml
└── README.md
```

依赖方向只有一条：`tui -> core`。core 内部再分为「领域模型 / 端口 / 适配器 / 编排」，
不会反向引用任何界面代码。

## 快速开始

需要 Python 3.10+。在 `agent/xAgent` 目录下执行：

```powershell
# 1. 安装依赖（同时安装 xagent 命令）
python -m pip install -e .

# 2. 准备配置
Copy-Item config.example.ini config.ini
# 编辑 config.ini，填入 base_url / model_name / api_key

# 3. 启动
python main.py
# 或
xagent
```

界面只显示运行状态，不会展示模型名称、接口地址或 API Key。
`config.ini` 已被 `.gitignore` 忽略，不会提交真实 Key。

### 常见问题

- **提示 API Key 无效**：确认 `agent/xAgent/config.ini` 的 `[llm] api_key` 已填写真实值，
  而不是 `config.example.ini` 里的占位符；本项目默认只读取本目录的 `config.ini`。
- **连接失败**：检查 `base_url` 是否可达；使用本机 Ollama 时通常不需要 API Key。
- 模型名称、接口地址和 Key 都不会出现在界面或日志中。

## TUI 操作

| 操作 | 说明 |
| --- | --- |
| Enter | 发送问题 |
| `/help` | 查看命令与工具列表 |
| `/clear` | 清空对话历史 |
| `/quit`、`/exit` | 退出 |
| Ctrl+C | 处理中取消当前回合；空闲时退出 |
| Ctrl+L | 清空对话 |
| Ctrl+Q | 退出 |

界面会把流式正文逐字写入对话区，工具调用与返回以独立消息块展示。
模型名称、接口地址与 API Key 只在 `config.ini` 中维护，不会显示在界面上。

## core 接口（Web / Desktop 复用入口）

core 对外的唯一门面是 `core.Agent`：

```python
from core import Agent, AppConfig, CancellationToken

agent = Agent(AppConfig.load())

def on_event(event):
    # 任意 UI 在这里把事件映射为自己的消息 / 信号 / 控件更新
    print(event)

result = agent.send("帮我看看当前目录", on_event=on_event)
```

`send()` 会阻塞到本轮结束，因此界面层需要把它放到**工作线程**（TUI 使用 Textual worker，
Web 可使用线程池或 async 包装，Desktop 可使用 QThread / 后台线程）。同一个 `Agent`
实例同一时刻只允许一轮对话，并发会话应为每个会话创建独立实例。

### 事件契约

| 事件 | 含义 |
| --- | --- |
| `TurnStarted(user_text)` | 一轮开始 |
| `AssistantDelta(round_index, text)` | 流式正文片段 |
| `AssistantCompleted(round_index, content)` | 某一轮模型输出结束 |
| `ToolCallStarted(round_index, tool_call_id, name, arguments)` | 开始执行工具 |
| `ToolCallFinished(round_index, tool_call_id, name, output, is_error)` | 工具执行完成 |
| `TurnFinished(ok, content, error, cancelled)` | 本轮结束（成功 / 失败 / 取消） |

`round_index` 从 0 开始；模型每发起一次工具调用并继续追问，就会进入下一轮。

### 新增 Web 适配层示意

```python
# web/app.py（示意，不在当前仓库内）
import asyncio
from concurrent.futures import ThreadPoolExecutor

from core import Agent, AppConfig

executor = ThreadPoolExecutor()

@app.websocket("/ws")
async def ws(socket: WebSocket):
    await socket.accept()
    agent = Agent(AppConfig.load())          # 每个连接独立会话
    loop = asyncio.get_running_loop()
    events: asyncio.Queue = asyncio.Queue()

    def on_event(event):
        # 从工作线程安全地把事件投递回事件循环
        loop.call_soon_threadsafe(events.put_nowait, event)

    def run_turn(text: str):
        agent.send(text, on_event=on_event)

    while True:
        text = await socket.receive_text()
        loop.run_in_executor(executor, run_turn, text)
        # 另一个协程持续消费 events 并 socket.send_json(...)
```

Desktop 适配层同理：只需要订阅同一组事件，把 `AssistantDelta` 追加到文本框，把
`ToolCallStarted` / `ToolCallFinished` 映射为列表项或日志，不需要触碰 core 的任何代码。

## 工具扩展

在 `core/tools/` 下新增一个模块，构造 `Tool` 并注册到 `build_default_registry()` 即可：

```python
from core.tools import Tool

def my_handler(args: dict) -> str:
    return "ok"

MY_TOOL = Tool(
    name="myTool",
    description="给模型看的工具说明",
    parameters={"type": "object", "properties": {}, "required": []},
    handler=my_handler,
)
```

`ToolRegistry` 会统一处理 JSON 入参解析和异常捕获，工具抛错不会终止会话。

## 内置工具

| 工具 | 说明 |
| --- | --- |
| `getDate` / `isLeapYear` / `getCurrentDirectory` | 日期时间、闰年判断、当前目录 |
| `listDirectory` / `getFileType` / `readTextFile` | 目录与文本文件读取 |
| `createFile` / `editFile` / `createDirectory` | 文件与目录创建、编辑 |
| `deleteFile` / `deleteDirectory` / `renameFileOrDirectory` | 删除与重命名 |
| `fetchWeb` | 用本地 `curl` 获取网页 HTML，并用 `trafilatura` 提取 Markdown 正文 |
| `searchWeb` | 调用百度千帆搜索 API，返回实时摘要、来源标题和 URL |
| `Runcli` | 以 `shell=False` 执行本地 CLI，返回 stdout、stderr 和退出码 |

`Runcli` 接收 `command` 与 `args` 列表，通过 `subprocess.run` 以运行 xAgent 的当前用户权限
执行，不经过 Shell 字符串拼接。默认超时 30 秒，stdout/stderr 各最多保留 10,000 个字符，
超出时会注明原始长度和截断情况。非零退出码会正常返回给 LLM 判断；未找到程序、权限错误、
超时等会返回明确错误。该工具不包含命令白名单、黑名单或审批机制，仅用于受控教学实验环境。

`fetchWeb` 要求系统 `PATH` 中存在 `curl`；`trafilatura` 会随 `pip install -e .` 自动安装。
工具会拒绝非 `http://` / `https://` 地址，并处理下载失败、超时、HTML 解析失败和正文为空的情况。

`searchWeb` 需要在 `config.ini` 的 `[search]` 小节配置 `baidu_qianfan_api_key`。工具会处理
未配置 Key、鉴权失败、限流、超时、网络错误和空结果，并自动截断超过 API 限制的 query。
同一轮对话中，完全相同的工具调用如果已经失败，后续重复调用会自动跳过，避免反复弹出相同错误
和重复等待。

## 配置

配置优先级：环境变量 > `config.ini` > 默认值。

| 配置项 | 环境变量 | 默认值 |
| --- | --- | --- |
| `[llm] base_url` | `XAGENT_BASE_URL` | `http://localhost:11434/v1` |
| `[llm] model_name` | `XAGENT_MODEL` | `qwen2.5` |
| `[llm] api_key` | `XAGENT_API_KEY` | 空 |
| `[llm] temperature` | `XAGENT_TEMPERATURE` | `0.7` |
| `[search] baidu_qianfan_api_key` | `XAGENT_SEARCH_API_KEY` | 空 |
| 配置文件路径 | `XAGENT_CONFIG` | `xAgent/config.ini` |

## 与 chat3.py 的对应关系

| chat3.py | xAgent |
| --- | --- |
| `SYSTEM_PROMPT`、`MAX_TOOL_ROUNDS` | `core/prompts.py` |
| `load_config()` | `core/config.py` |
| `TOOLS` + `TOOL_HANDLERS` + `dispatch_tool()` | `core/tools/` |
| `chat_once()`、SSE 解析、错误处理 | `core/llm/openai_compat.py` |
| `run_turn()`、历史快照与回滚 | `core/agent.py` + `core/conversation.py` |
| `main()`、`input()`、`print()` | `tui/app.py` + `tui/widgets.py` |

所有原有工具（`getDate`、`isLeapYear`、`getCurrentDirectory`、`listDirectory`、
`getFileType`、`readTextFile`、`createFile`、`editFile`、`createDirectory`、
`deleteDirectory`、`deleteFile`、`renameFileOrDirectory`）均已保留；另外新增
`fetchWeb` 用于读取网页正文，`searchWeb` 用于联网搜索，`Runcli` 用于调用本地命令行程序。
