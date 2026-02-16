"""Async Finnhub market data client with TTL cache and bounded concurrency."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

import finnhub

from ..config import get_settings
from ..models import ComputedValue, MarketSnapshot, MarketValue

# Module-level cache: (endpoint, symbol) -> (fetched_epoch, payload)
_cache: dict[tuple[str, str], tuple[float, dict]] = {}
_semaphore: asyncio.Semaphore | None = None
_client: finnhub.Client | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(get_settings().market_concurrency)
    return _semaphore


def _get_client() -> finnhub.Client:
    global _client
    if _client is None:
        _client = finnhub.Client(api_key=get_settings().finnhub_api_key)
    return _client


async def _call_in_thread(fn, *args, **kwargs):
    """Run a sync Finnhub call in a thread, respecting the concurrency semaphore."""
    async with _get_semaphore():
        return await asyncio.to_thread(fn, *args, **kwargs)


def _cache_get(endpoint: str, symbol: str) -> dict | None:
    """Return cached payload if within TTL, else None."""
    key = (endpoint, symbol)
    if key in _cache:
        fetched_epoch, payload = _cache[key]
        if time.time() - fetched_epoch < get_settings().market_ttl_seconds:
            return payload
        del _cache[key]
    return None


def _cache_set(endpoint: str, symbol: str, payload: dict) -> None:
    _cache[(endpoint, symbol)] = (time.time(), payload)


async def _fetch_quote(client: finnhub.Client, symbol: str) -> dict:
    cached = _cache_get("quote", symbol)
    if cached is not None:
        return cached
    data = await _call_in_thread(client.quote, symbol)
    _cache_set("quote", symbol, data)
    return data


async def _fetch_metric(client: finnhub.Client, symbol: str) -> dict:
    cached = _cache_get("metric", symbol)
    if cached is not None:
        return cached
    data = await _call_in_thread(client.company_basic_financials, symbol, "all")
    _cache_set("metric", symbol, data)
    return data


async def _fetch_profile(client: finnhub.Client, symbol: str) -> dict:
    cached = _cache_get("profile", symbol)
    if cached is not None:
        return cached
    data = await _call_in_thread(client.company_profile2, symbol=symbol)
    _cache_set("profile", symbol, data)
    return data


async def fetch_market_snapshot(symbol: str) -> MarketSnapshot:
    """Fetch current price, shares outstanding, and market cap for a ticker."""
    client = _get_client()
    now = datetime.now(UTC)
    store_raw = get_settings().store_raw_market_payload

    quote_data, metric_data, profile_data = await asyncio.gather(
        _fetch_quote(client, symbol),
        _fetch_metric(client, symbol),
        _fetch_profile(client, symbol),
    )

    # Price from quote endpoint
    current_price = quote_data.get("c")
    price_mv = MarketValue(
        metric="price",
        value=current_price,
        unit="USD",
        vendor="finnhub",
        symbol=symbol,
        endpoint="quote",
        as_of=datetime.fromtimestamp(quote_data.get("t", 0), tz=UTC)
        if quote_data.get("t")
        else None,
        fetched_at=now,
        raw=quote_data if store_raw else None,
    )

    # Shares outstanding from profile (in millions) or metric endpoint
    so_raw = profile_data.get("shareOutstanding")
    so_warnings: list[str] = []
    so_notes: list[str] = []

    if so_raw is not None and so_raw <= 0:
        so_warnings.append(
            f"Negative or zero shares outstanding from profile ({so_raw}); treated as None"
        )
        so_raw = None

    if so_raw is not None:
        # Finnhub profile returns shares in millions
        shares_value = so_raw * 1_000_000
        so_notes.append(f"Raw value {so_raw}M from profile endpoint, multiplied by 1e6")
    else:
        # Fallback to metric endpoint
        metric_values = metric_data.get("metric", {})
        so_raw = metric_values.get("shareOutstanding") or metric_values.get("sharesOutstanding")
        if so_raw is not None and so_raw < 1_000_000:
            shares_value = so_raw * 1_000_000
            so_notes.append(f"Raw value {so_raw} < 1M, treated as millions, multiplied by 1e6")
        else:
            shares_value = so_raw
        if so_raw is None:
            so_warnings.append("Shares outstanding not found in profile or metric endpoint")

    shares_mv = MarketValue(
        metric="shares_outstanding",
        value=shares_value,
        unit="shares",
        vendor="finnhub",
        symbol=symbol,
        endpoint="profile",
        fetched_at=now,
        raw=profile_data if store_raw else None,
        warnings=so_warnings,
        notes=so_notes,
    )

    # Market cap = price * shares
    if current_price is not None and shares_value is not None:
        mcap = current_price * shares_value
    else:
        mcap = None

    mcap_cv = ComputedValue(
        metric="market_cap",
        value=mcap,
        unit="USD",
        formula="price * shares_outstanding",
        components={"price": price_mv, "shares_outstanding": shares_mv},
    )

    company_name = profile_data.get("name", symbol)

    return MarketSnapshot(
        symbol=symbol,
        company_name=company_name,
        price=price_mv,
        shares_outstanding=shares_mv,
        market_cap=mcap_cv,
    )


async def fetch_market_snapshots(
    symbols: list[str],
) -> dict[str, MarketSnapshot | None]:
    """Fetch market snapshots for multiple tickers concurrently."""
    tasks = [fetch_market_snapshot(s) for s in symbols]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    output: dict[str, MarketSnapshot | None] = {}
    for symbol, result in zip(symbols, results):
        if isinstance(result, BaseException):
            output[symbol] = None
        else:
            output[symbol] = result
    return output


def clear_cache() -> None:
    """Clear the in-memory TTL cache and client. Useful for testing."""
    global _client
    _cache.clear()
    _client = None
