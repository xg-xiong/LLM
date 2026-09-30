"""list_pets 工具：列出宠物档案（对应后端 GET /api/v1/pets）。

参数全部可选，传了才拼入 query string。返回后端信封 data 的原样 JSON。
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from mcp.types import CallToolResult, TextContent

from petapi import PetApiError, PetClient

logger = logging.getLogger("tools.list_pets")

# 工具参数名 -> 后端 query 参数名（其余同名透传）
_BACKEND_KEY_MAP: dict[str, str] = {
    "owner_name": "ownerName",
    "owner_phone": "ownerPhone",
    "min_cost": "min",
    "max_cost": "max",
    "sort_by": "sortBy",
    "page_size": "pageSize",
}

_DOC = """列出宠物档案（只读查询，对应后端 GET /api/v1/pets）。

所有参数均可选，传了才作为筛选条件拼接到请求中：
- q：跨字段关键词检索（空格分词 AND）
- name：宠物名
- owner_name / owner_phone：主人姓名 / 主人电话
- species：种类（犬/猫/鸟/兔/鼠/龟/鱼等）
- breed：品种
- doctor：主治医生
- disease：疾病
- status：就诊状态（待就诊/就诊中/住院中/已康复/慢性病随访）
- min_cost / max_cost：总花费下限 / 上限（元）
- sort_by：排序字段（如 name / totalCost / createdAt）
- order：排序方向 asc / desc
- page：页码（默认 1）；page_size：每页条数（默认 20）

返回结构（后端信封 data 字段原样返回，JSON）：
{
  "items": [Pet, ...],   // 宠物列表；Pet 含 id/name/species/breed/gender/ageMonths/color/chipNo/
                         // ownerName/ownerPhone/ownerAddr/doctor/disease/status/allergy/note/
                         // records[]/charges[]/totalCost/visitCount/createdAt/updatedAt
  "total": 445,          // 命中总条数
  "page": 1,             // 当前页码
  "pageSize": 20,        // 每页条数
  "totalPages": 23,      // 总页数
  "totalCost": 123456.0  // 命中宠物总花费合计
}

空结果：items 为空数组、total 为 0，无分页异常。
失败（后端不可达/超时/非 2xx）：返回可读错误文本，并在结果中标记失败 is_error=true。
"""


def build_query(kwargs: dict[str, Any]) -> dict[str, Any]:
    """把工具参数映射为后端 query 参数，并丢弃值为 None 的项。"""
    query: dict[str, Any] = {}
    for key, value in kwargs.items():
        if value is not None:
            query[_BACKEND_KEY_MAP.get(key, key)] = value
    return query


def make_handler(client: PetClient) -> Callable[..., Awaitable[dict[str, Any]]]:
    """工厂：把共享后端客户端绑定到 list_pets 处理器（保持工具签名即 schema）。"""

    async def list_pets(
        q: str | None = None,
        name: str | None = None,
        owner_name: str | None = None,
        owner_phone: str | None = None,
        species: str | None = None,
        breed: str | None = None,
        doctor: str | None = None,
        disease: str | None = None,
        status: str | None = None,
        min_cost: float | None = None,
        max_cost: float | None = None,
        sort_by: str | None = None,
        order: str | None = None,
        page: int | None = None,
        page_size: int | None = None,
    ) -> dict[str, Any]:
        query = build_query(
            {
                "q": q,
                "name": name,
                "ownerName": owner_name,
                "ownerPhone": owner_phone,
                "species": species,
                "breed": breed,
                "doctor": doctor,
                "disease": disease,
                "status": status,
                "min": min_cost,
                "max": max_cost,
                "sortBy": sort_by,
                "order": order,
                "page": page,
                "pageSize": page_size,
            }
        )
        try:
            data = await client.list_pets(**query)
        except PetApiError as exc:
            logger.error("list_pets 调用失败：%s", exc)
            return CallToolResult(
                content=[TextContent(type="text", text=f"list_pets 调用失败：{exc}")],
                is_error=True,
            )
        logger.info("list_pets 命中 total=%s page=%s pageSize=%s", data.get("total"), data.get("page"), data.get("pageSize"))
        return data

    list_pets.__name__ = "list_pets"
    list_pets.__doc__ = _DOC
    return list_pets


__all__ = ["build_query", "make_handler"]