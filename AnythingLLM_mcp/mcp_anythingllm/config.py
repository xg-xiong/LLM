from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    base_url: str
    api_key: str
    workspace_slug: str | None
    default_mode: str
    default_top_n: int | None
    default_similarity_threshold: float | None
    host: str
    port: int
    stateless_http: bool
    json_response: bool
    request_timeout: float


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return value if value is not None and value != "" else default


def load_config() -> Config:
    api_key = _env("ALLM_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ALLM_API_KEY is not set. Create a .env file next to this package "
            "(see .env.example) or export the variable."
        )

    return Config(
        base_url=_env("ALLM_BASE_URL", "http://localhost:3001").rstrip("/"),
        api_key=api_key,
        workspace_slug=_env("ALLM_WORKSPACE_SLUG"),
        default_mode=_env("ALLM_MODE", "query"),
        default_top_n=_int_env("ALLM_TOP_N"),
        default_similarity_threshold=_float_env("ALLM_SIMILARITY_THRESHOLD"),
        host=_env("MCP_HOST", "127.0.0.1"),
        port=int(_env("MCP_PORT", "8000")),
        stateless_http=_bool_env("MCP_STATELESS", True),
        json_response=_bool_env("MCP_JSON_RESPONSE", False),
        request_timeout=float(_env("ALLM_TIMEOUT", "120")),
    )


def _int_env(name: str) -> int | None:
    value = _env(name)
    return int(value) if value is not None else None


def _float_env(name: str) -> float | None:
    value = _env(name)
    return float(value) if value is not None else None


def _bool_env(name: str, default: bool) -> bool:
    value = _env(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")