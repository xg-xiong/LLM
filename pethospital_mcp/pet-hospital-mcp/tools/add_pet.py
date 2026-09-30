"""add_pet 工具：新增宠物档案（对应后端 POST /api/v1/pets）。

注意：本工具是**写操作**（会向宠物医院数据库新增一条档案）。
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from mcp.types import CallToolResult, TextContent

from petapi import PetApiError, PetClient

logger = logging.getLogger("tools.add_pet")

# 工具参数名 -> 后端字段名（其余同名透传）
_BACKEND_KEY_MAP: dict[str, str] = {
    "owner_name": "ownerName",
    "owner_phone": "ownerPhone",
    "age_months": "ageMonths",
    "chip_no": "chipNo",
    "owner_addr": "ownerAddr",
}

_DOC = """新增一条宠物档案（写操作，对应后端 POST /api/v1/pets）。

必填参数：
- name：宠物名
- owner_name：主人姓名
- owner_phone：主人电话
- disease：疾病 / 主要诊断
- doctor：主治医生

可选参数（不传则留空）：
- species：种类（犬/猫/鸟/兔/鼠/龟/鱼等）
- breed：品种
- gender：性别（公/母）
- age_months：月龄
- color：毛色
- chip_no：芯片号
- owner_addr：主人住址
- status：就诊状态（待就诊/就诊中/住院中/已康复/慢性病随访）
- allergy：过敏史
- note：备注

返回：新建成功的宠物档案（后端信封 data，JSON），包含自动生成的 id
（形如 PET-001009）、createdAt/updatedAt，以及 totalCost=0、visitCount=0。

失败（必填缺失 / 后端校验不通过 / 后端不可达）：返回可读错误文本并标记失败
is_error=true，可据此修正参数后重试。
"""


def build_payload(kwargs: dict[str, Any]) -> dict[str, Any]:
    """把工具参数映射为后端字段，并丢弃值为 None 的项。"""
    payload: dict[str, Any] = {}
    for key, value in kwargs.items():
        if value is not None:
            payload[_BACKEND_KEY_MAP.get(key, key)] = value
    return payload


def make_handler(client: PetClient) -> Callable[..., Awaitable[dict[str, Any]]]:
    """工厂：把共享后端客户端绑定到 add_pet 处理器（保持工具签名即 schema）。"""

    async def add_pet(
        name: str,
        owner_name: str,
        owner_phone: str,
        disease: str,
        doctor: str,
        species: str | None = None,
        breed: str | None = None,
        gender: str | None = None,
        age_months: int | None = None,
        color: str | None = None,
        chip_no: str | None = None,
        owner_addr: str | None = None,
        status: str | None = None,
        allergy: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        payload = build_payload(
            {
                "name": name,
                "species": species,
                "breed": breed,
                "gender": gender,
                "ageMonths": age_months,
                "color": color,
                "chipNo": chip_no,
                "ownerName": owner_name,
                "ownerPhone": owner_phone,
                "ownerAddr": owner_addr,
                "doctor": doctor,
                "disease": disease,
                "status": status,
                "allergy": allergy,
                "note": note,
            }
        )
        try:
            data = await client.create_pet(payload)
        except PetApiError as exc:
            logger.error("add_pet 调用失败：%s", exc)
            return CallToolResult(
                content=[TextContent(type="text", text=f"add_pet 调用失败：{exc}")],
                is_error=True,
            )
        logger.info("add_pet 成功：id=%s name=%s ownerName=%s", data.get("id"), data.get("name"), data.get("ownerName"))
        return data

    add_pet.__name__ = "add_pet"
    add_pet.__doc__ = _DOC
    return add_pet


__all__ = ["build_payload", "make_handler"]