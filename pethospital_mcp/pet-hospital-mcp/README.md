# 宠物医院系统 MCP Server

把本地宠物医院系统（`pethospital.exe`）的 REST API 封装为 MCP 工具（以查询为主，含新增），
通过 **Streamable HTTP** 供其他 Agent 的 MCP Client 消费。

- 协议：**MCP 2026-07-28**（无状态协议核心，无 `initialize` 握手、无 `Mcp-Session-Id`）
- 语言/依赖：Python 3.10+，仅 `mcp>=2` + `httpx`
- 传输：Streamable HTTP，客户端访问 `http://127.0.0.1:18080/mcp`

> 当前已实现 2 个工具：`list_pets`（查询）、`add_pet`（新增）。代码结构已为后续更多工具预留扩展点。

---

## 一、目录结构

```text
pet-hospital-mcp/
├── pyproject.toml        # 依赖 mcp>=2、httpx；入口脚本
├── server.py             # MCPServer 装配 + mcp.run() 入口（注册 list_pets、add_pet）
├── petapi/
│   ├── __init__.py
│   ├── client.py         # 后端 REST 客户端（base_url、超时、统一信封解包、GET/POST）
│   └── types.py          # Pet / Record / Charge / PetListPage 数据模型
├── tools/
│   ├── __init__.py       # 工具注册中心（ALL_TOOL_FACTORIES）
│   ├── list_pets.py      # list_pets 工具（查询）
│   └── add_pet.py        # add_pet 工具（新增，写操作）
├── test_client.py        # list_pets 的 SDK 客户端验证脚本
├── test_add_pet.py       # add_pet 的 SDK 客户端验证脚本
└── README.md
```

分层约定：`petapi/` 负责 HTTP 与数据模型，`tools/` 只负责「参数映射 + 结果呈现」，
`server.py` 只负责装配与启动。

---

## 二、启动步骤

### 1. 启动数据源（后端 REST 服务）

```powershell
# 在 windows 目录下，默认监听 http://127.0.0.1:8080
.\pethospital.exe
```

### 2. 安装依赖并启动 MCP Server

```powershell
cd pet-hospital-mcp
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install "mcp>=2" httpx

# 默认：监听 127.0.0.1:18080，后端 127.0.0.1:8080，超时 10s
.\.venv\Scripts\python.exe server.py

# 自定义参数
.\.venv\Scripts\python.exe server.py -addr 127.0.0.1:18080 -upstream http://127.0.0.1:8080 -timeout 10
```

也可安装为命令：`pip install -e .` 后运行 `pet-hospital-mcp`。

启动成功后日志显示：

```text
MCP Server 启动：http://127.0.0.1:18080/mcp （后端 http://127.0.0.1:8080，timeout=10.0s）
Uvicorn running on http://127.0.0.1:18080
```

### 命令行参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `-addr` | `127.0.0.1:18080` | MCP Server 监听地址 `host:port` |
| `-upstream` | `http://127.0.0.1:8080` | 后端宠物医院 REST 服务地址 |
| `-timeout` | `10` | 后端请求超时（秒） |

---

## 三、接入其他 MCP Client

在支持 Streamable HTTP 的 MCP Client 中配置服务地址：

```json
{
  "mcpServers": {
    "pet-hospital": {
      "type": "streamable-http",
      "url": "http://127.0.0.1:18080/mcp"
    }
  }
}
```

请求需带 `MCP-Protocol-Version: 2026-07-28`；调用 `tools/call` 时带 `Mcp-Method: tools/call`
与 `Mcp-Name: list_pets`。使用官方 SDK 的 `Client` 会自动处理这些头。

---

## 四、工具：`list_pets`（查询）

对应后端 `GET /api/v1/pets`，列出宠物档案，支持筛选 / 排序 / 分页。

### 参数（全部可选，传了才作为筛选条件）

| 参数名 | 后端参数 | 说明 |
|---|---|---|
| `q` | q | 跨字段关键词检索（空格分词 AND） |
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
| `order` | order | asc / desc |
| `page` | page | 页码（默认 1） |
| `page_size` | pageSize | 每页条数（默认 20） |

### 返回

后端信封 `data` 字段原样 JSON 返回：

```json
{
  "items": [ { "id": "...", "...": "...", "totalCost": 123.4, "visitCount": 2 } ],
  "total": 1008,
  "page": 1,
  "pageSize": 20,
  "totalPages": 51,
  "totalCost": 3680172.85
}
```

- 空结果：`items` 为空数组、`total` 为 0，不是错误。
- 失败（后端不可达 / 超时 / 非 2xx）：返回可读错误文本并标记 `isError=true`。

---

## 五、工具：`add_pet`（新增，写操作）

对应后端 `POST /api/v1/pets`，新增一条宠物档案。**注意这是写操作，会修改数据库。**

### 参数

必填：

| 参数名 | 后端字段 | 说明 |
|---|---|---|
| `name` | name | 宠物名 |
| `owner_name` | ownerName | 主人姓名 |
| `owner_phone` | ownerPhone | 主人电话 |
| `disease` | disease | 疾病 / 主要诊断 |
| `doctor` | doctor | 主治医生 |

可选（不传则留空）：

| 参数名 | 后端字段 | 说明 |
|---|---|---|
| `species` | species | 种类（犬/猫/鸟/兔/鼠/龟/鱼…） |
| `breed` | breed | 品种 |
| `gender` | gender | 性别（公/母） |
| `age_months` | ageMonths | 月龄 |
| `color` | color | 毛色 |
| `chip_no` | chipNo | 芯片号 |
| `owner_addr` | ownerAddr | 主人住址 |
| `status` | status | 就诊状态（待就诊/就诊中/住院中/已康复/慢性病随访） |
| `allergy` | allergy | 过敏史 |
| `note` | note | 备注 |

### 返回

后端信封 `data`（新建的宠物档案，JSON），含自动生成的 `id`（如 `PET-001009`）、
`createdAt`/`updatedAt`，以及 `totalCost: 0`、`visitCount: 0`：

```json
{
  "id": "PET-001009",
  "name": "旺财",
  "species": "犬",
  "ownerName": "张三",
  "ownerPhone": "13800001111",
  "doctor": "李医生",
  "disease": "急性肠胃炎",
  "totalCost": 0,
  "visitCount": 0,
  "createdAt": "2026-09-18T11:14:25+08:00"
}
```

- 缺必填参数：MCP 框架在调用前拦截，返回校验错误并标记 `isError=true`。
- 后端校验失败（如电话格式非法）：返回后端可读错误信息并标记 `isError=true`，可据此修正重试。
- 后端不可达 / 超时：返回可读错误文本并标记 `isError=true`。

---

## 六、验证

### 1. SDK 客户端脚本（推荐）

```powershell
.\.venv\Scripts\python.exe test_client.py http://127.0.0.1:18080/mcp
.\.venv\Scripts\python.exe test_add_pet.py http://127.0.0.1:18080/mcp
```

- `test_client.py`：`list_tools`（应含 `list_pets`）与多组 `call_tool`（空参、`species=犬`、
  `owner_name`+`sortBy=totalCost&order=desc`、`q` 检索、`page_size=5&page=2`、
  `min_cost/max_cost`、`status`+`breed`）。
- `test_add_pet.py`：`list_tools`（应含 `add_pet`）、正常新增、用 `list_pets` 查回、
  缺必填与后端校验失败的错误路径。**会创建测试数据，请自行清理。**

### 2. curl（2026-07-28 协议行为）

请求体需带 `params._meta`（命名空间键），HTTP 头需与 body 一致：

```powershell
# server/discover：应返回 supportedVersions:["2026-07-28"]、resultType:"complete"、serverInfo
curl.exe -s -X POST "http://127.0.0.1:18080/mcp" `
  -H "MCP-Protocol-Version: 2026-07-28" -H "Mcp-Method: server/discover" `
  -H "Accept: application/json, text/event-stream" -H "Content-Type: application/json" `
  --data-binary '{"jsonrpc":"2.0","id":1,"method":"server/discover","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientCapabilities":{}}}}'

# tools/list：应确定性有序、含 ttlMs/cacheScope、含 list_pets 与 add_pet、schema 含全部参数
curl.exe -s -X POST "http://127.0.0.1:18080/mcp" `
  -H "MCP-Protocol-Version: 2026-07-28" -H "Mcp-Method: tools/list" `
  -H "Accept: application/json, text/event-stream" -H "Content-Type: application/json" `
  --data-binary '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientCapabilities":{}}}}'

# tools/call：应返回 resultType:"complete"
curl.exe -s -X POST "http://127.0.0.1:18080/mcp" `
  -H "MCP-Protocol-Version: 2026-07-28" -H "Mcp-Method: tools/call" -H "Mcp-Name: list_pets" `
  -H "Accept: application/json, text/event-stream" -H "Content-Type: application/json" `
  --data-binary '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"list_pets","arguments":{"species":"犬","sort_by":"totalCost","order":"desc","page_size":3},"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientCapabilities":{}}}}'

# tools/call add_pet：新增宠物（写操作；Mcp-Name 为 add_pet）
curl.exe -s -X POST "http://127.0.0.1:18080/mcp" `
  -H "MCP-Protocol-Version: 2026-07-28" -H "Mcp-Method: tools/call" -H "Mcp-Name: add_pet" `
  -H "Accept: application/json, text/event-stream" -H "Content-Type: application/json" `
  --data-binary '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"add_pet","arguments":{"name":"旺财","owner_name":"张三","owner_phone":"13800001111","disease":"急性肠胃炎","doctor":"李医生","species":"犬"},"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientCapabilities":{}}}}'

# GET / DELETE 应返回 405（Allow: POST）
curl.exe -s -i -X GET    "http://127.0.0.1:18080/mcp" -H "MCP-Protocol-Version: 2026-07-28"
curl.exe -s -i -X DELETE "http://127.0.0.1:18080/mcp" -H "MCP-Protocol-Version: 2026-07-28"
```

### 3. 语法检查

```powershell
.\.venv\Scripts\python.exe -m compileall server.py petapi tools test_client.py test_add_pet.py
```

---

## 七、协议实现要点（MCP 2026-07-28）

- **无状态核心**：每个请求自包含；服务以 `stateless_http=True` 运行，不建立会话、
  不返回 `Mcp-Session-Id`，忽略客户端传入的该头。
- **`server/discover`**：由 SDK 自动提供，返回 `supportedVersions:["2026-07-28"]`、
  能力（`tools`）与身份；版本不匹配返回 `UnsupportedProtocolVersionError`（-32022）。
- **`_meta` 元数据**：所有结果携带 `io.modelcontextprotocol/serverInfo`。
- **`resultType`**：所有结果带 `resultType:"complete"`。
- **Streamable HTTP**：遵循 `MCP-Protocol-Version`、`Mcp-Method`、`Mcp-Name` 头语义；
  非 POST（GET/DELETE）返回 405 并带 `Allow: POST`。
- **`tools/list` 缓存**：`CacheHint(ttl_ms=60000, scope="public")`，返回 `ttlMs` 与 `cacheScope`；
  工具按注册顺序确定性返回。
- **JSON Schema 2020-12**：工具 schema 由 Python 类型提示自动生成（2020-12 兼容写法）。
- 不实现已废弃的 roots/sampling/logging，不做资源订阅。

---

## 八、后续扩展规划（本次不实现）

新增一个工具只需三步，`server.py` 无需改动：

1. `petapi/client.py` 添加后端调用方法（返回信封 `data` 原始 dict）；
2. `tools/` 新建文件，定义 `make_handler(client)` 返回带类型注解与中文 docstring 的 async 函数；
3. `tools/__init__.py` 的 `ALL_TOOL_FACTORIES` 追加该工厂。

预留的 14 个工具方向：

| 工具 | 对应后端接口 |
|---|---|
| `get_pet` | `GET /api/v1/pets/{id}` |
| `search_pets` | `GET /api/v1/pets/search?q=` |
| `list_by_owner` | `GET /api/v1/pets/by-owner` |
| `list_by_doctor` | `GET /api/v1/pets/by-doctor` |
| `list_by_species` | `GET /api/v1/pets/by-species` |
| `list_by_disease` | `GET /api/v1/pets/by-disease` |
| `list_by_status` | `GET /api/v1/pets/by-status` |
| `top_spenders` | `GET /api/v1/pets/top-spenders` |
| `cost_range` | `GET /api/v1/pets/cost-range` |
| `get_records` | `GET /api/v1/pets/{id}/records` |
| `get_charges` | `GET /api/v1/pets/{id}/charges` |
| `get_summary` | `GET /api/v1/pets/{id}/summary` |
| `get_stats` | `GET /api/v1/stats` |
| `get_meta` | `GET /api/v1/meta` |
