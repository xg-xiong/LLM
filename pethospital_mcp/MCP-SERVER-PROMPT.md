# 任务：为宠物医院系统开发 MCP Server（Python，MCP 2026-07-28 最新规范）

## 目标
开发一个 **Python 编写的 MCP Server**，把本地宠物医院系统的 REST API 数据封装为 MCP Tools，
供其他 Agent 的 MCP Client 通过 **Streamable HTTP** 传输消费。**只读查询**，不做任何写操作。

底层 REST 服务是 `D:\opencode_xg\windows` 下的 `pethospital.exe`（Go 标准库编写，
默认监听 `http://127.0.0.1:8080`）。开发期间先手工启动它作为数据源。

## 开发节奏（重要）
本工程后续会一次性补齐全部功能，但**本次迭代只交付 MVP**：

**MVP 范围 = 只实现 1 个工具：`list_pets`（列出宠物，支持各种参数筛选）。**
- 唯一工具 `list_pets`，覆盖 `GET /api/v1/pets` 的全部筛选/排序/分页参数，见下方「MVP 工具定义」。
- 代码结构必须为后续 14 个工具（详情/搜索/按医生/按种类/病历/消费/统计等）预留清晰的扩展点
  （统一的后端 REST 客户端 + 统一的工具注册模块），但**现阶段不要实现它们**。
- 验收时只验证 `list_pets`；`tools/list` 中应只出现 `list_pets`。

## 硬性要求（最新协议规范）
必须使用 **MCP 规范 2026-07-28**（官方最高版本），不得回退到旧版会话/握手模型：

1. **无状态协议核心**：禁止 `initialize`/`notifications/initialized` 握手，禁止
   `Mcp-Session-Id` 头与任何会话状态。每个请求自包含。
2. **`server/discover`**：实现该 RPC（SDK 自动提供），广告协议版本（含 `2026-07-28`）、
   能力（`tools`）与身份信息；版本不匹配返回 `UnsupportedProtocolVersionError`。
3. **`_meta` 元数据**：响应携带 `io.modelcontextprotocol/serverInfo`。
4. **`resultType`**：所有结果带 `resultType:"complete"`。
5. **Streamable HTTP 请求头**：遵循 `MCP-Protocol-Version`、`Mcp-Method`、`Mcp-Name`
   头语义；忽略 `Mcp-Session-Id`，GET/DELETE 返回 405。
6. **`tools/list` 缓存**：支持 `_meta[:cacheable]` 与 `ttlMs`；工具按确定性顺序返回。
7. **JSON Schema 2020-12**：所有工具 schema 遵循该标准（由 Python 类型提示自动生成）。
8. 不实现已废弃的 roots/sampling/logging，不做资源订阅。

## 技术栈与依赖
- Python **3.10+**；依赖仅 `mcp`（官方 Python SDK，**v2.x**，即 pip install 默认版本，
  唯一支持 2026-07-28 的新主线）+ `httpx`（mcp 依赖自带，用于调后端 REST）。
- 虚拟环境：`python -m venv .venv`，用 `uv` 或 `pip install "mcp>=2"` 安装。

## SDK 用法基线（照此设计，勿走 v1.x 旧教程）
参照官方文档 https://py.sdk.modelcontextprotocol.io/ 的 v2 写法：
- `from mcp.server import MCPServer`；`mcp = MCPServer("pet-hospital-mcp")`
- 工具用装饰器声明，**函数签名 + 类型提示 + 中文 docstring 即 schema**：
  `@mcp.tool()` 修饰一个带参数类型注解和 docstring 的 `async def`。
- 服务入口：`mcp.run(transport="streamable-http", host="127.0.0.1", port=18080)`，
  客户端访问 `http://127.0.0.1:18080/mcp`。
- 若需显式控制（如扩展能力声明、缓存 ttl），查阅 v2 API 文档在 `MCPServer` 配置。

## MVP 工具定义：list_pets
映射后端 `GET /api/v1/pets`（响应信封 `{"code":200,"message":"ok","data":{...},"time":"..."}`，
取值 `data`，再取其中的列表字段）。参数全部可选，按是否存在拼装 query string：

| 参数名 | 后端参数 | 说明 |
|---|---|---|
| `q` | q | 跨字段关键词 |
| `name` | name | 宠物名 |
| `owner_name` | ownerName | 主人姓名 |
| `owner_phone` | ownerPhone | 主人电话 |
| `species` | species | 种类（犬/猫/鸟/兔/鼠/龟/鱼…） |
| `breed` | breed | 品种 |
| `doctor` | doctor | 主治医生 |
| `disease` | disease | 疾病 |
| `status` | status | 就诊状态（待就诊/就诊中/住院中/已康复/慢性病随访） |
| `min_cost` | min | 总花费下限 |
| `max_cost` | max | 总花费上限 |
| `sort_by` | sortBy | 排序字段（如 name/totalCost/createdAt） |
| `order` | order | asc/desc |
| `page` | page | 页码（默认 1） |
| `page_size` | pageSize | 每页条数（默认 20） |

返回：把后端 `data` 中宠物列表（含 `totalCost`、`visitCount` 派生子段）**原样 JSON 返回**，
并用 docstring 说明返回结构、空结果行为与分页信息，帮助 Agent 理解。错误（超时/后端不可达/
非 2xx）转为可读错误文本并在结果中标记失败。

## 工程结构（为后续全量功能预留扩展点）
```
pet-hospital-mcp/
├── pyproject.toml        # 依赖 mcp>=2，入口脚本
├── server.py             # MCPServer 装配 + mcp.run() 入口（MVP 只注册 list_pets）
├── petapi/
│   ├── __init__.py
│   ├── client.py         # 后端 REST 客户端（base_url、超时、统一信封解包）
│   └── types.py          # Pet 数据模型（字段与后端一致）
└── tools/
    ├── __init__.py
    └── list_pets.py      # list_pets 工具（后续每工具一个文件）
```
> `petapi/` 与 `tools/` 分层：后续加 `get_pet`、`search_pets`、`get_stats` 等只需在
> `petapi/` 加方法、`tools/` 加文件、`server.py` 加一行注册。**本次不要写它们。**

## 命令行/配置
`-addr`（默认 `127.0.0.1:18080`）、`-upstream`（默认 `http://127.0.0.1:8080`）、
`-timeout`（默认 10s）。用 `argparse` 实现即可。

## 验证方案（必须亲自执行通过）
1. 先启动 `pethospital.exe`（后端 8080），再启动本 server。
2. 用 SDK 自带客户端脚本验证（写一个临时的 async client）：
   `Client("http://127.0.0.1:18080/mcp")` → `list_tools()`（应只有 `list_pets`）→
   `call_tool("list_pets", {...})` 跑多个参数组合：
   - 空参（全量分页第一页）
   - `species=犬` 过滤
   - `owner_name` 过滤 + `sort_by=totalCost&order=desc`
   - `q` 全文检索；`page_size=5&page=2` 分页
3. 用 curl 验证 2026-07-28 行为：
   - `server/discover`：确认返回协议版本 2026-07-28 与服务端信息。
   - `tools/list`：确认确定性有序、schema 为 2020-12 且含全部筛选参数。
   - `tools/call`（list_pets）：确认 `resultType:"complete"`。
   - `GET /mcp` 返回 405。请求头示例：`MCP-Protocol-Version: 2026-07-28` + `Mcp-Method` + `Mcp-Name`。
4. `python -m compileall` 通过，无语法错误；日志用 `logging` 模块输出便于排查。

## 交付物
可运行工程 + README（启动步骤、接入其他 MCP Client 的 URL 配置、`list_pets` 工具说明与
curl 示例、后续扩展规划）。仅依赖 `mcp>=2`，无其他非必要依赖。
```