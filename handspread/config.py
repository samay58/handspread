"""Configuration from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    finnhub_api_key: str
    market_ttl_seconds: int = 300
    market_concurrency: int = 8
    store_raw_market_payload: bool = False

    model_config = {"env_prefix": "", "case_sensitive": False}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
