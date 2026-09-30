"""统一的后端 REST 客户端。

- base_url：后端服务地址（默认 http://127.0.0.1:8080）
- timeout：请求超时（秒）
- 统一解包响应信封，出错抛 PetApiError（由工具层转为可读错误并标记失败）

后续扩展点：在此类中按需新增方法，例如：
    async def get_pet(self, pet_id: str) -> dict: ...
    async def search_pets(self, **query) -> dict: ...
所有方法保持「返回信封 data 原始 dict」，由 tools/ 层做参数映射与结果呈现。
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .types import PetListPage

logger = logging.getLogger("petapi")

DEFAULT_BASE_URL = "http://127.0.0.1:8080"
DEFAULT_TIMEOUT = 10.0


class PetApiError(RuntimeError):
    """后端调用失败：不可达 / 超时 / 非 2xx / 响应信封异常。"""


class PetClient:
    """宠物医院后端 REST 客户端（查询 + 新增）。"""

    def __init__(self, base_url: str = DEFAULT_BASE_URL, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    @staticmethod
    def _clean(data: dict[str, Any] | None) -> dict[str, Any]:
        """丢弃值为 None 的字段，避免拼出无意义的 query/body。"""
        if not data:
            return {}
        return {k: v for k, v in data.items() if v is not None}

    @staticmethod
    def _unwrap(body: Any, url: str) -> dict[str, Any]:
        """校验统一信封并返回 body。成功码接受任意 2xx（新增返回 201）。"""
        if not isinstance(body, dict):
            raise PetApiError(f"后端响应不是 JSON 对象：{url}")
        code = body.get("code")
        if not isinstance(code, int) or not (200 <= code < 300):
            raise PetApiError(f"后端响应信封异常：code={code} message={body.get('message')}")
        return body

    @staticmethod
    def _error_detail(resp: httpx.Response) -> str:
        """从错误响应中尽量提取后端可读的 message。"""
        try:
            body = resp.json()
            if isinstance(body, dict) and body.get("message"):
                return str(body["message"])
        except ValueError:
            pass
        return resp.text[:200]

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """发送请求并解包统一信封，返回 body。"""
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.request(
                    method,
                    url,
                    params=self._clean(query),
                    json=self._clean(json_body) if json_body is not None else None,
                )
        except httpx.HTTPError as exc:
            raise PetApiError(f"无法访问后端 {url}：{exc!r}") from exc

        if resp.status_code < 200 or resp.status_code >= 300:
            raise PetApiError(f"后端返回 {resp.status_code}：{self._error_detail(resp)}")

        try:
            body = resp.json()
        except ValueError as exc:
            raise PetApiError(f"后端响应不是合法 JSON：{resp.text[:200]}") from exc

        return self._unwrap(body, url)

    @staticmethod
    def _extract_data(body: dict[str, Any]) -> dict[str, Any]:
        data = body.get("data")
        if not isinstance(data, dict):
            raise PetApiError("后端响应缺少 data 字段")
        return data

    async def list_pets(self, **query: Any) -> dict[str, Any]:
        """调用 GET /api/v1/pets，返回信封的 data 字段（原样 dict）。

        query 接受后端原生参数名（q / ownerName / sortBy / pageSize …）。
        """
        body = await self._request_json("GET", "/api/v1/pets", query=query)
        data = self._extract_data(body)
        try:
            PetListPage.model_validate(data)
        except Exception as exc:  # noqa: BLE001 - 结构校验失败只告警，仍透传原样数据
            logger.warning("响应结构校验告警（仍透传原样数据）：%s", exc)
        return data

    async def create_pet(self, payload: dict[str, Any]) -> dict[str, Any]:
        """调用 POST /api/v1/pets 新增宠物，返回信封 data（新建的宠物档案）。

        payload 接受后端原生字段名（name / ownerName / ownerPhone / disease / doctor …）。
        后端成功时返回 code=201。
        """
        body = await self._request_json("POST", "/api/v1/pets", json_body=payload)
        return self._extract_data(body)
