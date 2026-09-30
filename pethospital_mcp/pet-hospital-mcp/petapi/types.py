"""Pet 数据模型：字段与后端 pethospital.exe 完全一致（用于结构校验与文档）。

后端以 camelCase 命名；这里用 Field(alias=...) 对齐，同时允许以 Python 风格
snake_case 访问。所有字段均为后端实际返回的 JSON 键。

派生字段（只读，后端自动汇总）：
- totalCost  总花费 = charges[].amount 之和
- visitCount 就诊次数 = records 条数
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Base(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
        arbitrary_types_allowed=True,
    )


class Record(Base):
    """历史病历。"""

    id: str = ""
    visitDate: str = ""
    doctor: str = ""
    diagnosis: str = ""
    symptoms: str = ""
    treatment: str = ""
    prescription: list[str] = Field(default_factory=list)
    weightKg: float = 0.0
    temperature: float = 0.0
    followUp: str = ""
    charge: float = 0.0
    createdAt: str = ""


class Charge(Base):
    """消费明细。"""

    id: str = ""
    item: str = ""
    category: str = ""
    amount: float = 0.0
    doctor: str = ""
    date: str = ""


class Pet(Base):
    """宠物档案主档（含历史病历与消费明细，以及派生字段）。"""

    id: str = ""
    name: str = ""
    species: str = ""
    breed: str = ""
    gender: str = ""
    ageMonths: int = 0
    color: str = ""
    chipNo: str | None = None
    ownerName: str = ""
    ownerPhone: str = ""
    ownerAddr: str = ""
    doctor: str = ""
    disease: str = ""
    status: str = ""
    allergy: str = ""
    note: str | None = None
    records: list[Record] = Field(default_factory=list)
    charges: list[Charge] = Field(default_factory=list)
    totalCost: float = 0.0
    visitCount: int = 0
    createdAt: str = ""
    updatedAt: str = ""


class PetListPage(Base):
    """GET /api/v1/pets 响应中 data 字段的分页结构。"""

    items: list[Pet] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    pageSize: int = 20
    totalPages: int = 0
    totalCost: float = 0.0


class Envelope(Base):
    """后端统一响应信封：{"code": 200, "message": "ok", "data": {...}, "time": "..."}。"""

    code: int = 0
    message: str = ""
    data: dict = Field(default_factory=dict)
    time: str = ""