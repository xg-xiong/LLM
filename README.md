# LLM · MCP 项目合集

本仓库收录三个基于 **MCP（Model Context Protocol）** 的项目，围绕「把本地业务系统暴露给大模型 / Agent」这一主题展开：

- 两个 **Python MCP Server**（基于官方 Python SDK v2.x，Streamable HTTP 传输）
- 一个 **纯前端管理台 + 本地 REST 业务系统**（作为 MCP Server 的数据源）

三个项目既可独立运行，也可组合成一条完整链路：

```text
Agent / MCP Client
      │
      ├───► AnythingLLM_mcp  ──►  AnythingLLM (localhost:3001)  ──►  向量库 + LLM
      │                              ▲
      │                              │ 文档上传 / 工作区管理
      │                        AnythingLLMServer (浏览器管理台)
      │
      └───► pet-hospital-mcp ──►  pethospital.exe (localhost:8080) ──►  data/pet.db
```

---

## 目录

- [项目总介绍](#项目总介绍)
- [目录结构](#目录结构)
- [子项目简介](#子项目简介)
  - [1. AnythingLLM_mcp](#1-anythingllm_mcp)
  - [2. AnythingLLMServer](#2-anythingllmserver)
  - [3. pethospital_mcp](#3-pethospital_mcp)
- [环境依赖](#环境依赖)
- [启动步骤](#启动步骤)
- [快速验证](#快速验证)
- [安全提示](#安全提示)
- [常见问题](#常见问题)

---

## 项目总介绍

### 共同点

| 维度 | 说明 |
| --- | --- |
| 协议 | MCP **2026-07-28**（无状态协议核心：无 `initialize` 握手、无 `Mcp-Session-Id`，每个请求自包含） |
| 传输 | **Streamable HTTP**（非 STDIO），监听 `127.0.0.1`，仅 POST 有效 |
| 语言 | MCP Server 均为 **Python 3.10+**，依赖仅 `mcp>=2` + `httpx` |
| 业务后端 | 均**无鉴权、仅监听本机**，定位为本地开发 / 演示 / 教学 |
| 数据 | 均落在本地文件：向量数据由 AnythingLLM 管理，业务数据为单文件 `data/pet.db` |

### 技术要点

- **无状态 MCP**：两个 Server 均以 `stateless_http=True` 运行，不建立会话、不返回会话 ID。
- **`tools/list` 缓存**：`pet-hospital-mcp` 声明 `CacheHint(ttl_ms=60000, scope="public")`，工具按注册顺序确定性返回。
- **JSON Schema 2020-12**：工具 schema 由 Python 类型注解 + docstring 自动生成。
- **分层约定**：`pet-hospital-mcp` 中 `petapi/` 只管 HTTP 与数据模型，`tools/` 只管参数映射与结果呈现，`server.py` 只管装配与启动——新增工具无需改动 `server.py`。
- **单文件可迁移**：宠物医院后端仅需「可执行文件 + `data/pet.db`」两个文件即可搬到任何电脑，目标机无需安装 Go 或数据库。

---

## 目录结构

```text
LLM/
├── README.md                        # 本文档
├── .gitignore
│
├── AnythingLLM_mcp/                 # ① Python MCP Server：问答 AnythingLLM 工作区
│   ├── mcp_anythingllm/
│   │   ├── __init__.py              # 版本号 0.1.0
│   │   ├── __main__.py              # 入口：python -m mcp_anythingllm
│   │   ├── config.py                # .env 配置加载
│   │   ├── anythingllm.py           # AnythingLLM Developer API 异步客户端
│   │   └── server.py                # MCPServer 装配 + ask_workspace 工具
│   ├── requirements.txt
│   ├── .env.example                 # 配置模板（复制为 .env 后填写）
│   └── .env                         # 本地真实配置（含 API Key，已被 .gitignore 排除）
│
├── AnythingLLMServer/               # ② 纯前端 AnythingLLM 管理台（单文件 HTML）
│   ├── index.html                   # 上传 / 文档树 / 工作区管理，无构建步骤
│   └── sample.txt                   # 上传与向量化功能的测试文档
│
└── pethospital_mcp/                 # ③ 宠物医院：Go 后端 exe + Python MCP Server
    ├── pethospital.exe              # Go 标准库编译的 REST 后端（Windows 64 位，网页已内嵌）
    ├── data/pet.db                  # 单文件嵌入式数据库（全部业务数据）
    ├── README.md                    # 后端完整接口与数据模型文档
    ├── README-Windows.md            # Windows 运行说明
    ├── MCP-SERVER-PROMPT.md         # MCP Server 的原始需求与验收标准
    ├── LICENSE                      # MIT
    └── pet-hospital-mcp/            # Python MCP Server
        ├── pyproject.toml
        ├── server.py                # MCPServer 装配 + 启动入口
        ├── petapi/                  # 后端 REST 客户端 + 数据模型
        ├── tools/                   # list_pets / add_pet 两个工具
        ├── test_client.py           # list_pets 验证脚本
        ├── test_add_pet.py          # add_pet 验证脚本（会写入数据）
        └── README.md                # MCP Server 完整文档
```

> 说明：宠物医院后端的 **Go 源码不在本仓库**，仓库内仅提供已编译的 Windows 可执行文件。
> 源码结构（`main.go` / `internal/model` / `internal/store` / `internal/api`）见 `pethospital_mcp/README.md`。

---

## 子项目简介

### 1. AnythingLLM_mcp

把 **AnythingLLM** 的 Developer API 封装为一个 MCP Server，让 Agent 可以直接向指定工作区提问，并拿到「答案 + 引用片段」。

| 项 | 值 |
| --- | --- |
| 协议 / 传输 | MCP 2026-07-28，Streamable HTTP |
| 默认监听 | `http://127.0.0.1:8000/mcp` |
| 上游后端 | AnythingLLM，默认 `http://localhost:3001` |
| 工具 | `ask_workspace`（唯一一个） |

**工具 `ask_workspace`**

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `message` | string | 必填 | 向工作区提出的问题 |
| `mode` | `query` \| `chat` \| `automatic` | `query` | `query` 严格检索、只用文档回答；`chat` 混入模型通用知识；`automatic` 在模型支持时走原生工具调用 |
| `top_n` | int (1–20) | `ALLM_TOP_N` | 检索的上下文片段数量 |
| `similarity_threshold` | float (0–1) | — | 片段被采用的最低向量相似度 |

返回结构化结果：`answer`（答案）、`sources[]`（`title` + `chunk`，即引用出处）、`mode`、`workspace`。

**行为约定**

- 工作区解析：优先用 `.env` 中的 `ALLM_WORKSPACE_SLUG`；未配置且后端恰好只有 1 个工作区时自动选中；存在多个则报错并提示设置该变量。
- 上游返回 403 判定为 API Key 无效；无答案且无引用时提示「工作区可能没有相关上下文」。

---

### 2. AnythingLLMServer

**注意：这不是一个后端服务，而是一个零依赖的单文件网页管理台。**

它用原生 HTML + CSS + JavaScript 直接调用 AnythingLLM 的 REST API（`http://localhost:3001/api`），用于在没有官方前端 UI 的情况下完成日常管理操作。直接用浏览器打开 `index.html` 即可使用，无需构建、无需服务器。

三个功能页签：

| 页签 | 能力 |
| --- | --- |
| **上传** | 选择目标工作区 → 选择文件 → 上传并触发向量化嵌入（`POST /api/v1/document/upload`） |
| **文档** | 左侧递归文档树（文件夹嵌套）、右侧文件列表；支持删除单个文档、删除整个文件夹 |
| **工作区** | 列出全部工作区（名称 + slug）；支持创建、重命名、删除 |

**特点**

- 纯前端，API Key 由使用者在页面顶部输入框粘贴（`type="password"`，不回显、不落盘）。
- 所有用户数据经 `textContent` 渲染，天然规避 XSS。
- `sample.txt` 是配套的测试文档，用于验证「上传 → 切片 → 向量化」链路是否正常。

---

### 3. pethospital_mcp

由**数据源后端**和 **MCP Server** 两部分组成。

#### 3.1 数据源：`pethospital.exe`（Go 标准库）

一个本地宠物医院管理系统，启动后同时提供网页操作界面和完整 REST 接口。

| 项 | 值 |
| --- | --- |
| 语言 / 依赖 | Go **1.22+**，只用标准库，零第三方依赖 |
| 默认监听 | `http://127.0.0.1:8080` |
| 接口数量 | 29 个（查询 / 新增 / 删除 / 批量 / 导出 / 统计） |
| 鉴权 | 无（明文 HTTP，仅本机） |
| 存储 | 单文件 `data/pet.db`，自研嵌入式引擎 |

**核心特性**

- **网页已内嵌进可执行文件**：浏览器打开根路径即为完整操作界面（列表 / 搜索 / 筛选 / 排序 / 分页、新增编辑删除、查看历史病历与消费明细、经营统计卡片）。
- **单文件数据库引擎**：追加写日志（append-only）+ CRC32 校验 + 内存索引；自动压实回收垃圾；写临时文件后 `rename` 保证原子性、`fsync` 落盘；断电导致的半条记录会被检测并自动截断修复。
- **可复现模拟数据**：固定随机种子，覆盖 17 个字段维度、46 种真实兽医疾病、12 位医生、7 个种类、10 个城市；疾病与物种匹配、医生按专长分配，重症患者带 2–5 次随访。
- **单文件迁移**：复制「exe + `data/pet.db`」到任何电脑即可运行，无需 Go、数据库或运行时。

> 完整接口清单、数据模型、数据库文件格式见 `pethospital_mcp/README.md`。

#### 3.2 `pet-hospital-mcp`（Python MCP Server）

把上述 REST API 封装为 MCP 工具。

| 项 | 值 |
| --- | --- |
| 协议 / 传输 | MCP 2026-07-28，Streamable HTTP |
| 默认监听 | `http://127.0.0.1:18080/mcp` |
| 上游后端 | `http://127.0.0.1:8080` |
| 工具 | `list_pets`（查询）、`add_pet`（新增，写操作） |

| 工具 | 对应接口 | 说明 |
| --- | --- | --- |
| `list_pets` | `GET /api/v1/pets` | 支持 15 个可选参数：跨字段关键词 `q`、宠物名、主人姓名/电话、种类、品种、医生、疾病、状态、总花费区间 `min_cost`/`max_cost`、排序 `sort_by`+`order`、分页 `page`/`page_size`。返回 `items` / `total` / `totalPages` / `totalCost`。空结果不是错误。 |
| `add_pet` | `POST /api/v1/pets` | **写操作，会修改数据库。** 必填 `name`、`owner_name`、`owner_phone`、`disease`、`doctor`；可选 `species`、`breed`、`gender`、`age_months`、`color`、`chip_no`、`owner_addr`、`status`、`allergy`、`note`。返回新档案（含自动生成的 `id`）。 |

**分层与扩展**：新增工具只需三步——`petapi/client.py` 加方法 → `tools/` 新建文件定义 `make_handler(client)` → `tools/__init__.py` 的 `ALL_TOOL_FACTORIES` 追加一项，`server.py` 无需改动。`README.md` 中列出了 14 个预留工具方向（`get_pet`、`search_pets`、`top_spenders`、`get_stats` 等）。

---

## 环境依赖

### 通用

| 依赖 | 版本要求 | 说明 |
| --- | --- | --- |
| OS | Windows 10 / 11（`pethospital.exe` 为 64 位） | 其他平台需自行交叉编译后端 |
| Python | **3.10+**（实测 3.13.7） | 两个 MCP Server 共用 |
| 浏览器 | Chrome / Edge / Firefox 现代版本 | 用于 AnythingLLM 管理台与宠物医院网页界面 |
| Git | 2.x | 可选 |

### MCP Server 依赖

两个 Server 的 Python 依赖几乎一致：

```text
mcp>=2            # 官方 Python SDK v2.x，唯一支持 MCP 2026-07-28 的主线
httpx>=0.27       # 异步 HTTP 客户端（调用上游 REST API）
```

`AnythingLLM_mcp` 额外需要：

```text
uvicorn>=0.38     # ASGI 服务器（mcp 依赖已带入）
python-dotenv>=1.0  # 读取 .env 配置
```

对应 `AnythingLLM_mcp/requirements.txt`：

```text
mcp>=2.2,<3
uvicorn>=0.38
httpx>=0.28
python-dotenv>=1.0
```

已验证可用的组合（两个 venv 实测一致）：

| 包 | 实测版本 |
| --- | --- |
| Python | 3.13.7 |
| `mcp` | 2.2.0 |
| `httpx` | 0.28.1 |
| `uvicorn` | 0.53.0 |
| `pydantic` | 2.13.5 |
| `python-dotenv` | 1.2.3（仅 `AnythingLLM_mcp`） |

> `mcp` 必须为 **v2.x**。v1.x 不支持 MCP 2026-07-28 的 `server/discover` 与无状态协议核心，照 v1 教程写会走错。

### AnythingLLM 服务端

`AnythingLLM_mcp` 需要一个**已经在运行的 AnythingLLM 实例**：

| 项 | 值 |
| --- | --- |
| 下载 | [AnythingLLM 官方仓库](https://github.com/Mintplex-Labs/anything-llm) |
| 默认端口 | `3001`（Server 模式） |
| 向量数据库 | 内置 LanceDB（无需额外安装） |
| LLM / 嵌入模型 | 启动后在 Web UI 中配置 |
| API Key | 在 Web UI → Settings → Developer API 中生成 |

### 端口占用总览

启动全部服务前请确认以下端口未被占用：

| 端口 | 服务 |
| --- | --- |
| `3001` | AnythingLLM |
| `8000` | `AnythingLLM_mcp`（MCP） |
| `8080` | `pethospital.exe`（宠物医院后端 + 网页界面） |
| `18080` | `pet-hospital-mcp`（MCP） |

---

## 启动步骤

> 以下命令在 **Windows PowerShell** 中执行。

### 步骤 0 · 克隆仓库

```powershell
git clone https://github.com/xg-xiong/LLM.git
cd LLM
```

### 步骤 1 · 启动宠物医院后端（`pethospital.exe`）

```powershell
cd pethospital_mcp
.\pethospital.exe
```

首次运行会自动新建 `data\pet.db`。想灌入演示数据：

```powershell
.\pethospital.exe -seed -count 2000    # 8 条精选 + 2000 条随机模拟数据
```

浏览器打开 <http://127.0.0.1:8080/> 即可看到操作界面。终端会实时打印访问日志，`Ctrl+C` 安全退出（自动压实数据库并落盘）。

常用参数：

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `-addr` | `127.0.0.1:8080` | 监听地址 |
| `-db` | `./data/pet.db` | 数据库路径 |
| `-seed` | 关 | 首次写入 8 条精选数据 |
| `-count N` | — | 配合 `-seed` 生成 N 条随机数据 |
| `-no-color` | 关 | 关闭 ANSI 彩色输出 |

### 步骤 2 · 启动宠物医院 MCP Server

```powershell
cd pethospital_mcp\pet-hospital-mcp

# 创建虚拟环境并安装依赖
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install "mcp>=2" httpx

# 启动（默认监听 127.0.0.1:18080，后端 127.0.0.1:8080）
.\.venv\Scripts\python.exe server.py
```

启动成功日志：

```text
MCP Server 启动：http://127.0.0.1:18080/mcp （后端 http://127.0.0.1:8080，timeout=10.0s）
Uvicorn running on http://127.0.0.1:18080
```

可选参数：

```powershell
.\.venv\Scripts\python.exe server.py -addr 127.0.0.1:18080 -upstream http://127.0.0.1:8080 -timeout 10
```

也可以安装为命令后直接运行：

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
pet-hospital-mcp
```

**验证：**

```powershell
# SDK 客户端脚本（list_add_pet 会写入测试数据，请自行清理）
.\.venv\Scripts\python.exe test_client.py http://127.0.0.1:18080/mcp
.\.venv\Scripts\python.exe test_add_pet.py http://127.0.0.1:18080/mcp

# 语法检查
.\.venv\Scripts\python.exe -m compileall server.py petapi tools test_client.py test_add_pet.py
```

### 步骤 3 · 启动 AnythingLLM 服务端

按 [AnythingLLM 官方文档](https://docs.anythingllm.com/installation-desktop) 安装并启动，默认监听 `3001`。

启动后在 Web UI 中依次完成：

1. **Settings → Embedder**：选择嵌入模型（首次使用需下载模型）
2. **Settings → LLM**：配置大模型 Provider 与 API Key
3. **Settings → Vector Database**：保持默认 LanceDB
4. **Settings → Developer API**：生成 API Key（`AnythingLLM_mcp` 需要）
5. **Workspace**：新建一个工作区

### 步骤 4 · 使用 AnythingLLM 管理台准备知识库

直接用浏览器打开：

```text
AnythingLLMServer\index.html
```

1. 在页面顶部粘贴刚才生成的 API Key，点「加载」
2. 在「工作区」页签创建一个工作区（`AnythingLLM_mcp` 建议只保留一个，或记录其 slug）
3. 在「上传」页签选择目标工作区，上传 `AnythingLLMServer\sample.txt`
4. 在「文档」页签确认文件已出现在文档树中

> 也可以直接使用 AnythingLLM 官方 Web UI 完成以上操作；本管理台是官方 UI 不可用时的替代方案。

### 步骤 5 · 启动 AnythingLLM MCP Server

```powershell
cd AnythingLLM_mcp

# 创建虚拟环境并安装依赖
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 准备配置
Copy-Item .env.example .env
notepad .env        # 至少填写 ALLM_API_KEY

# 启动（默认监听 127.0.0.1:8000）
.\.venv\Scripts\python.exe -m mcp_anythingllm
```

`.env` 配置项：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `ALLM_BASE_URL` | `http://localhost:3001` | AnythingLLM 服务地址 |
| `ALLM_API_KEY` | 无 | **必填**，Developer API Key，缺失则启动即报错 |
| `ALLM_WORKSPACE_SLUG` | 空 | 目标工作区 slug；留空则要求后端恰好只有 1 个工作区 |
| `ALLM_MODE` | `query` | `ask_workspace` 的默认模式 |
| `ALLM_TOP_N` | 空 | 默认检索片段数 |
| `ALLM_SIMILARITY_THRESHOLD` | 空 | 默认相似度阈值 |
| `ALLM_TIMEOUT` | `120` | 调用 AnythingLLM 的超时（秒） |
| `MCP_HOST` | `127.0.0.1` | MCP Server 监听地址 |
| `MCP_PORT` | `8000` | MCP Server 监听端口 |
| `MCP_STATELESS` | `true` | 无状态模式 |
| `MCP_JSON_RESPONSE` | `false` | 返回纯 JSON 而非 SSE |

### 步骤 6 · 接入 MCP Client

在支持 **Streamable HTTP** 的 MCP Client（如 Claude Desktop、opencode 等）中配置：

```json
{
  "mcpServers": {
    "pet-hospital": {
      "type": "streamable-http",
      "url": "http://127.0.0.1:18080/mcp"
    },
    "anythingllm": {
      "type": "streamable-http",
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

**说明**：请求需携带 `MCP-Protocol-Version: 2026-07-28`；调用 `tools/call` 时还需 `Mcp-Method: tools/call` 与 `Mcp-Name: <工具名>` 头。使用官方 SDK 的 `Client` 会自动处理这些头。对 `http://127.0.0.1:8000/mcp` 发 `GET` / `DELETE` 会返回 `405`（`Allow: POST`），这是预期行为。

### 启动顺序小结

```text
1. pethospital.exe            → 127.0.0.1:8080   （宠物医院数据源）
2. pet-hospital-mcp/server.py → 127.0.0.1:18080  （宠物医院 MCP）
3. AnythingLLM                → localhost:3001    （AnythingLLM 服务端）
4. index.html（浏览器）        → 管理知识库
5. mcp_anythingllm            → 127.0.0.1:8000   （AnythingLLM MCP）
6. MCP Client 配置两个 URL     → 开始对话
```

`pet-hospital-mcp` 依赖后端已启动才能正常调用，但后端晚于 MCP Server 启动也可以（调用时才报错）。`AnythingLLM_mcp` 同理。

---

## 快速验证

两个 MCP Server 都实现了 MCP 2026-07-28 的无状态协议核心，可用 `curl` 直接冒烟测试，无需 MCP Client。

**公共请求头**（两者一致）：

```text
MCP-Protocol-Version: 2026-07-28
Accept: application/json, text/event-stream
Content-Type: application/json
```

### 冒烟测试 `pet-hospital-mcp`（:18080）

```powershell
# server/discover —— 应返回 supportedVersions:["2026-07-28"]、serverInfo
curl.exe -s -X POST "http://127.0.0.1:18080/mcp" `
  -H "MCP-Protocol-Version: 2026-07-28" -H "Mcp-Method: server/discover" `
  -H "Accept: application/json, text/event-stream" -H "Content-Type: application/json" `
  --data-binary '{"jsonrpc":"2.0","id":1,"method":"server/discover","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28"}}}'

# tools/list —— 应含 list_pets 与 add_pet，且返回 ttlMs / cacheScope
curl.exe -s -X POST "http://127.0.0.1:18080/mcp" `
  -H "MCP-Protocol-Version: 2026-07-28" -H "Mcp-Method: tools/list" `
  -H "Accept: application/json, text/event-stream" -H "Content-Type: application/json" `
  --data-binary '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28"}}}'

# tools/call list_pets —— 应返回 resultType:"complete"
curl.exe -s -X POST "http://127.0.0.1:18080/mcp" `
  -H "MCP-Protocol-Version: 2026-07-28" -H "Mcp-Method: tools/call" -H "Mcp-Name: list_pets" `
  -H "Accept: application/json, text/event-stream" -H "Content-Type: application/json" `
  --data-binary '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"list_pets","arguments":{"species":"犬","sort_by":"totalCost","order":"desc","page_size":3},"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28"}}}'

# GET / DELETE 应返回 405（Allow: POST）
curl.exe -s -i -X GET "http://127.0.0.1:18080/mcp" -H "MCP-Protocol-Version: 2026-07-28"
```

### 冒烟测试 `AnythingLLM_mcp`（:8000）

```powershell
# tools/list —— 应仅含 ask_workspace
curl.exe -s -X POST "http://127.0.0.1:8000/mcp" `
  -H "MCP-Protocol-Version: 2026-07-28" -H "Mcp-Method: tools/list" `
  -H "Accept: application/json, text/event-stream" -H "Content-Type: application/json" `
  --data-binary '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28"}}}'

# tools/call ask_workspace —— 回答内容取决于已上传并向量化的文档
curl.exe -s -X POST "http://127.0.0.1:8000/mcp" `
  -H "MCP-Protocol-Version: 2026-07-28" -H "Mcp-Method: tools/call" -H "Mcp-Name: ask_workspace" `
  -H "Accept: application/json, text/event-stream" -H "Content-Type: application/json" `
  --data-binary '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"ask_workspace","arguments":{"message":"这个文档讲了什么？","mode":"query"},"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28"}}}'
```

### 后端健康检查

```powershell
Invoke-RestMethod http://127.0.0.1:8080/health          # 宠物医院后端
Invoke-RestMethod http://127.0.0.1:8080/api/v1/stats     # 经营统计
Invoke-RestMethod http://127.0.0.1:8080/api/v1/endpoints # 29 个接口清单
```

### 语法自检

```powershell
cd pethospital_mcp\pet-hospital-mcp
.\.venv\Scripts\python.exe -m compileall server.py petapi tools test_client.py test_add_pet.py
```

---

## 安全提示

- **两个后端均无鉴权、仅明文 HTTP**，只监听 `127.0.0.1`。**请勿直接暴露到公网。**
- **API Key 不要提交到仓库。** 本仓库的 `.gitignore` 已排除 `.env` 与 `.env.*`（保留 `.env.example` 模板）。管理台 `index.html` 中的 API Key 输入框需手动粘贴，且不写入 `localStorage`。
- 提交前请确认 `git status` 中不含 `.env`：

  ```powershell
  git status --short
  git check-ignore -v AnythingLLM_mcp\.env
  ```

- AnythingLLM API Key 在后台可随时吊销重置；若曾泄露过，请立即在 `Settings → Developer API` 中重新生成。

---

## 常见问题

**Q：`AnythingLLM_mcp` 启动报 `ALLM_API_KEY is not set`**
未创建 `.env` 或未填写该变量。执行 `Copy-Item .env.example .env` 后填入 Key。

**Q：调用 `ask_workspace` 报「有多个工作区」**
`.env` 中设置 `ALLM_WORKSPACE_SLUG` 指定目标工作区。slug 可在管理台「工作区」页签查看。

**Q：`ask_workspace` 返回「无答案且无引用」**
`query` 模式下工作区确实没有相关内容。请先确认文档已上传并完成向量化，或改用 `mode="chat"`（会混入模型通用知识）。

**Q：`pet-hospital-mcp` 调用报「无法访问后端」**
`pethospital.exe` 未启动，或端口不是默认的 8080。用 `-upstream` 指定实际地址。

**Q：`test_add_pet.py` 报数据异常**
该脚本**会真实写入数据库**。建议在测试库上运行，或事后手动清理新增的档案。

**Q：Windows 双击 `pethospital.exe` 窗口闪退**
改用命令行启动以查看错误输出；端口被占用时加 `-addr 127.0.0.1:9090`；中文乱码时先执行 `chcp 65001`。

**Q：`tools/list` 返回 405**
必须用 `POST`，且 `Accept` 头同时包含 `application/json` 与 `text/event-stream`。

---

## 许可

`pethospital_mcp` 部分基于 MIT 许可证，见 `pethospital_mcp/LICENSE`。