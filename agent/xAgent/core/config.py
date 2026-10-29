# -*- coding: utf-8 -*-
"""配置加载。

配置来源优先级（高 -> 低）：
1. 环境变量 XAGENT_BASE_URL / XAGENT_MODEL / XAGENT_API_KEY / XAGENT_TEMPERATURE /
   XAGENT_SEARCH_API_KEY
2. config.ini 的 [llm] / [search] 段（路径可由 XAGENT_CONFIG 指定）
3. 内置默认值

core 只负责解析配置，不打印提示；提示由各 UI 适配层决定。
"""
from __future__ import annotations

import configparser
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.ini"


@dataclass(frozen=True, slots=True)
class LLMConfig:
    base_url: str = "http://localhost:11434/v1"
    model_name: str = "qwen2.5"
    api_key: str = ""
    temperature: float = 0.7

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)


@dataclass(frozen=True, slots=True)
class SearchConfig:
    baidu_qianfan_api_key: str = ""

    @property
    def has_api_key(self) -> bool:
        return bool(self.baidu_qianfan_api_key)


@dataclass(frozen=True, slots=True)
class AppConfig:
    llm: LLMConfig
    search: SearchConfig = field(default_factory=SearchConfig)
    source: Path | None = None

    @classmethod
    def load(
        cls,
        path: str | Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> AppConfig:
        env = os.environ if env is None else env
        config_path = Path(
            path or env.get("XAGENT_CONFIG") or DEFAULT_CONFIG_PATH
        ).expanduser()

        parser = configparser.ConfigParser()
        parser.read(str(config_path), encoding="utf-8-sig")
        section = parser["llm"] if parser.has_section("llm") else {}
        search_section = parser["search"] if parser.has_section("search") else {}

        base_url = _pick(env, "XAGENT_BASE_URL", section, "base_url", "http://localhost:11434/v1")
        model_name = _pick(env, "XAGENT_MODEL", section, "model_name", "qwen2.5")
        api_key = _pick(env, "XAGENT_API_KEY", section, "api_key", "")
        temperature_raw = _pick(env, "XAGENT_TEMPERATURE", section, "temperature", "0.7")
        search_api_key = _pick(
            env,
            "XAGENT_SEARCH_API_KEY",
            search_section,
            "baidu_qianfan_api_key",
            "",
        )

        try:
            temperature = float(temperature_raw)
        except (TypeError, ValueError):
            temperature = 0.7

        return cls(
            llm=LLMConfig(
                base_url=str(base_url).strip().rstrip("/"),
                model_name=str(model_name).strip(),
                api_key=str(api_key).strip(),
                temperature=temperature,
            ),
            search=SearchConfig(
                baidu_qianfan_api_key=str(search_api_key).strip(),
            ),
            source=config_path.resolve(),
        )


def _pick(
    env: Mapping[str, str],
    env_key: str,
    section: Mapping[str, str],
    config_key: str,
    default: str,
) -> str:
    if env.get(env_key):
        return env[env_key]
    value = section.get(config_key) if section else None
    return default if value is None else value
