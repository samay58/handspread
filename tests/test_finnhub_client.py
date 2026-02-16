"""Tests for the Finnhub market data client."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from handspread.market.finnhub_client import (
    clear_cache,
    fetch_market_snapshot,
    fetch_market_snapshots,
)
from handspread.models import ComputedValue, MarketSnapshot, MarketValue


def _mock_client(quote=None, profile=None, metric=None):
    """Build a mock finnhub.Client with canned responses for quote, profile, and metric."""
    client = MagicMock()
    client.quote.return_value = quote or {"c": 150.0, "t": 1700000000}
    client.company_profile2.return_value = profile or {
        "shareOutstanding": 24.3,
        "name": "Test Corp",
    }
    client.company_basic_financials.return_value = metric or {"metric": {}}
    return client


def _mock_settings():
    """Build a mock Settings object with default test values."""
    s = MagicMock()
    s.finnhub_api_key = "test-key"
    s.market_ttl_seconds = 300
    s.market_concurrency = 8
    s.store_raw_market_payload = False
    return s


@pytest.fixture(autouse=True)
def _clean_state():
    """Clear module-level cache and reset semaphore before each test."""
    clear_cache()
    # Reset the module-level semaphore so each test gets a fresh one
    import handspread.market.finnhub_client as mod

    mod._semaphore = None
    yield
    clear_cache()
    mod._semaphore = None


class TestSnapshotBasic:
    @pytest.mark.asyncio
    async def test_snapshot_basic(self):
        """Mock quote + profile + metric, verify MarketSnapshot fields."""
        client = _mock_client()
        with (
            patch("handspread.market.finnhub_client._get_client", return_value=client),
            patch("handspread.market.finnhub_client.get_settings", return_value=_mock_settings()),
        ):
            snap = await fetch_market_snapshot("TEST")

        assert snap.symbol == "TEST"
        assert snap.price.value == 150.0
        assert snap.company_name == "Test Corp"
        assert snap.market_cap.value is not None


class TestSharesMillionsConversion:
    @pytest.mark.asyncio
    async def test_shares_millions_conversion(self):
        """Profile returns 24.3 (millions), verify * 1_000_000."""
        client = _mock_client(profile={"shareOutstanding": 24.3, "name": "X"})
        with (
            patch("handspread.market.finnhub_client._get_client", return_value=client),
            patch("handspread.market.finnhub_client.get_settings", return_value=_mock_settings()),
        ):
            snap = await fetch_market_snapshot("TEST")

        assert snap.shares_outstanding.value == 24_300_000


class TestSharesFallbackToMetric:
    @pytest.mark.asyncio
    async def test_shares_fallback_to_metric(self):
        """Profile returns None for shares, metric endpoint has it."""
        client = _mock_client(
            profile={"shareOutstanding": None, "name": "X"},
            metric={"metric": {"sharesOutstanding": 50.0}},
        )
        with (
            patch("handspread.market.finnhub_client._get_client", return_value=client),
            patch("handspread.market.finnhub_client.get_settings", return_value=_mock_settings()),
        ):
            snap = await fetch_market_snapshot("TEST")

        # 50.0 < 1_000_000, so treated as millions
        assert snap.shares_outstanding.value == 50_000_000


class TestCacheHit:
    @pytest.mark.asyncio
    async def test_cache_hit(self):
        """Call twice, verify second call doesn't invoke client methods again."""
        client = _mock_client()
        with (
            patch("handspread.market.finnhub_client._get_client", return_value=client),
            patch("handspread.market.finnhub_client.get_settings", return_value=_mock_settings()),
        ):
            await fetch_market_snapshot("CACHE_TEST")
            initial_quote_calls = client.quote.call_count
            await fetch_market_snapshot("CACHE_TEST")

        # Second call should use cache, not call client again
        assert client.quote.call_count == initial_quote_calls


class TestCacheExpiry:
    @pytest.mark.asyncio
    async def test_cache_expiry(self):
        """Set TTL to 0, verify cache miss forces re-fetch."""
        client = _mock_client()
        settings = _mock_settings()
        settings.market_ttl_seconds = 0
        with (
            patch("handspread.market.finnhub_client._get_client", return_value=client),
            patch("handspread.market.finnhub_client.get_settings", return_value=settings),
        ):
            await fetch_market_snapshot("EXPIRE_TEST")
            await fetch_market_snapshot("EXPIRE_TEST")

        # Both calls should hit the client (cache expired immediately)
        assert client.quote.call_count >= 2


class TestNegativeSharesWarning:
    @pytest.mark.asyncio
    async def test_negative_shares_warning(self):
        """Mock negative shares, verify warning added and shares treated as None."""
        client = _mock_client(
            profile={"shareOutstanding": -5.0, "name": "BadData Corp"},
            metric={"metric": {}},
        )
        with (
            patch("handspread.market.finnhub_client._get_client", return_value=client),
            patch("handspread.market.finnhub_client.get_settings", return_value=_mock_settings()),
        ):
            snap = await fetch_market_snapshot("BAD")

        assert snap.shares_outstanding.value is None
        assert any("Negative or zero" in w for w in snap.shares_outstanding.warnings)


class TestFetchSnapshotsPartialFailure:
    @pytest.mark.asyncio
    async def test_partial_failure(self):
        """One ticker succeeds, one raises. Dict has None for failed ticker."""
        with patch("handspread.market.finnhub_client.fetch_market_snapshot") as mock_single:

            async def side_effect(sym):
                if sym == "BAD":
                    raise RuntimeError("API error")
                return await _make_snapshot_async(sym)

            mock_single.side_effect = side_effect
            result = await fetch_market_snapshots(["GOOD", "BAD"])

        assert result["GOOD"] is not None
        assert result["GOOD"].symbol == "GOOD"
        assert result["BAD"] is None


async def _make_snapshot_async(symbol):
    """Async helper to build a MarketSnapshot for the partial failure test."""
    now = datetime.now(UTC)
    p = MarketValue(
        metric="price",
        value=100.0,
        unit="USD",
        vendor="finnhub",
        symbol=symbol,
        endpoint="quote",
        fetched_at=now,
    )
    s = MarketValue(
        metric="shares_outstanding",
        value=1_000_000,
        unit="shares",
        vendor="finnhub",
        symbol=symbol,
        endpoint="profile",
        fetched_at=now,
    )
    mcap = ComputedValue(
        metric="market_cap",
        value=100_000_000,
        unit="USD",
        formula="price * shares_outstanding",
    )
    return MarketSnapshot(
        symbol=symbol,
        company_name=f"{symbol} Corp",
        price=p,
        shares_outstanding=s,
        market_cap=mcap,
    )
