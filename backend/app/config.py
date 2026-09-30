"""Central configuration. Everything environment-driven, no secrets in code.

LLM wrapper is provider-agnostic:
- LLM_PROVIDER=mock       -> deterministic offline provider (demo/CI)
- LLM_PROVIDER=openai     -> any OpenAI-compatible endpoint (Qwen cloud, vLLM, SGLang)
  LLM_BASE_URL / LLM_MODEL / LLM_API_KEY decide the target.
Swapping cloud Qwen for self-hosted open weights = changing 3 env vars.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache


def _bool(v: str | None, default: bool = False) -> bool:
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    # app
    app_name: str = "Check-up Intelligence — PRIME"
    debug: bool = False

    # database: sqlite by default (demo), Postgres in production via DATABASE_URL
    database_url: str = "sqlite:///./data/medcheck.db"

    # uploads
    upload_dir: str = "./data/uploads"
    max_upload_mb: int = 20

    # LLM wrapper (OpenAI-compatible protocol)
    llm_provider: str = "mock"  # mock | openai
    llm_base_url: str = "https://api.example.com/v1"
    llm_model: str = "qwen3.8-max"
    llm_api_key: str = ""
    llm_timeout_s: int = 120
    llm_json_mode: bool = True

    # pipeline behaviour
    # require patient confirmation before values enter the health map (always True in MVP)
    require_confirmation: bool = True
    # min chars of extractable text before we treat a PDF as a scan (OCR/multimodal stage)
    min_text_chars: int = 60

    # CORS (clinic LAN / same origin)
    cors_origins: str = "*"

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def require_llm_key(self) -> None:
        if self.llm_provider == "openai" and not self.llm_api_key:
            raise RuntimeError("LLM_API_KEY is required when LLM_PROVIDER=openai")


def _env(name: str, default: str) -> str:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


@lru_cache
def get_settings() -> Settings:
    return Settings(
        app_name=_env("APP_NAME", "Check-up Intelligence — PRIME"),
        debug=_bool(os.environ.get("DEBUG"), False),
        database_url=_env("DATABASE_URL", "sqlite:///./data/medcheck.db"),
        upload_dir=_env("UPLOAD_DIR", "./data/uploads"),
        max_upload_mb=int(_env("MAX_UPLOAD_MB", "20")),
        llm_provider=_env("LLM_PROVIDER", "mock"),
        llm_base_url=_env("LLM_BASE_URL", "https://api.example.com/v1"),
        llm_model=_env("LLM_MODEL", "qwen3.8-max"),
        llm_api_key=os.environ.get("LLM_API_KEY", ""),
        llm_timeout_s=int(_env("LLM_TIMEOUT_S", "120")),
        llm_json_mode=_bool(os.environ.get("LLM_JSON_MODE", "true"), True),
        min_text_chars=int(_env("MIN_TEXT_CHARS", "60")),
        cors_origins=_env("CORS_ORIGINS", "*"),
    )


def reset_settings_cache() -> None:
    get_settings.cache_clear()
