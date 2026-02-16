"""Configuration from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    finnhub_api_key: str
    market_ttl_seconds: int = Field(default=300, ge=0)
    market_concurrency: int = Field(default=8, ge=1)
    store_raw_market_payload: bool = False

    model_config = {
        "env_prefix": "",
        "case_sensitive": False,
        "env_file": ".env",
        "extra": "ignore",
    }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings for the current process."""
    return Settings()
