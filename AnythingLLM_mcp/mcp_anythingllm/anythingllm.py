from __future__ import annotations

from dataclasses import dataclass, field

import httpx


class AnythingLLMError(RuntimeError):
    """Raised when AnythingLLM cannot fulfill a request."""


@dataclass
class ChatSource:
    title: str
    chunk: str


@dataclass
class ChatResult:
    text_response: str
    sources: list[ChatSource] = field(default_factory=list)
    response_type: str | None = None
    error: str | None = None


class AnythingLLMClient:
    """Small async client for the AnythingLLM Developer API (http://.../api)."""

    def __init__(self, base_url: str, api_key: str, timeout: float = 120.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
            },
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def list_workspaces(self) -> list[dict]:
        data = await self._request("GET", "/api/v1/workspaces")
        workspaces = data.get("workspaces") or []
        if not isinstance(workspaces, list):
            raise AnythingLLMError(f"Unexpected workspaces payload: {data!r}")
        return workspaces

    async def get_workspace(self, slug: str) -> dict:
        data = await self._request("GET", f"/api/v1/workspace/{slug}")
        workspace = data.get("workspace")
        if workspace is None:
            raise AnythingLLMError(f"Workspace {slug!r} not found: {data!r}")
        return workspace

    async def chat(
        self,
        slug: str,
        message: str,
        mode: str = "query",
        *,
        top_n: int | None = None,
        similarity_threshold: float | None = None,
    ) -> ChatResult:
        body: dict[str, object] = {"message": message, "mode": mode, "reset": True}
        if top_n is not None:
            body["topN"] = top_n
        if similarity_threshold is not None:
            body["similarityThreshold"] = similarity_threshold

        data = await self._request("POST", f"/api/v1/workspace/{slug}/chat", json=body)
        sources = [
            ChatSource(
                title=str(source.get("title", "")),
                chunk=str(source.get("chunk", "")),
            )
            for source in (data.get("sources") or [])
            if isinstance(source, dict)
        ]
        return ChatResult(
            text_response=str(data.get("textResponse", "") or ""),
            sources=sources,
            response_type=data.get("type") if isinstance(data.get("type"), str) else None,
            error=data.get("error") if isinstance(data.get("error"), str) else None,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, object] | None = None,
    ) -> dict:
        try:
            response = await self._client.request(method, f"{self._base_url}{path}", json=json)
        except httpx.HTTPError as exc:
            raise AnythingLLMError(f"AnythingLLM request failed: {exc}") from exc

        if response.status_code == 403:
            raise AnythingLLMError("AnythingLLM rejected the API key (HTTP 403)")
        if response.status_code in (400, 404):
            raise AnythingLLMError(f"AnythingLLM {response.status_code} for {path}: {response.text[:300]}")
        if response.status_code >= 500:
            raise AnythingLLMError(f"AnythingLLM server error {response.status_code} for {path}: {response.text[:300]}")
        if response.status_code not in (200, 201):
            raise AnythingLLMError(f"AnythingLLM unexpected status {response.status_code} for {path}")

        try:
            return response.json()
        except ValueError as exc:
            raise AnythingLLMError(f"AnythingLLM returned non-JSON for {path}") from exc