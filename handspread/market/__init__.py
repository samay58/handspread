"""Market data layer (Finnhub)."""

from .finnhub_client import fetch_market_snapshot, fetch_market_snapshots

__all__ = ["fetch_market_snapshot", "fetch_market_snapshots"]
