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


class TestNonPositivePriceWarning:
    @pytest.mark.asyncio
    async def test_zero_price_treated_as_none(self):
        """Zero price should be treated as missing to avoid nonsense market cap."""
        client = _mock_client(
            quote={"c": 0.0, "t": 1700000000},
            profile={"shareOutstanding": 10.0, "name": "ZeroPrice Co"},
        )
        with (
            patch("handspread.market.finnhub_client._get_client", return_value=client),
            patch("handspread.market.finnhub_client.get_settings", return_value=_mock_settings()),
        ):
            snap = await fetch_market_snapshot("ZERO")

        assert snap.price.value is None
        assert snap.market_cap.value is None
        assert any("Negative or zero price" in w for w in snap.price.warnings)

    @pytest.mark.asyncio
    async def test_non_numeric_price_treated_as_none(self):
        """Malformed price should be treated as missing, not crash."""
        client = _mock_client(
            quote={"c": "not-a-number", "t": 1700000000},
            profile={"shareOutstanding": 10.0, "name": "BadPrice Co"},
        )
        with (
            patch("handspread.market.finnhub_client._get_client", return_value=client),
            patch("handspread.market.finnhub_client.get_settings", return_value=_mock_settings()),
        ):
            snap = await fetch_market_snapshot("BADPRICE")

        assert snap.price.value is None
        assert snap.market_cap.value is None
        assert any("Non-numeric price" in w for w in snap.price.warnings)


class TestMarketCapFromProfile:
    """Vendor-provided market cap from profile endpoint should take precedence."""

    @pytest.mark.asyncio
    async def test_vendor_market_cap_used(self):
        """Profile returns marketCapitalization; verify it's used instead of price * shares."""
        client = _mock_client(
            profile={
                "shareOutstanding": 25900.0,  # ADR: 25.9B ordinary shares
                "marketCapitalization": 950000,  # $950B in millions
                "name": "TSM Corp",
            },
            quote={"c": 200.0, "t": 1700000000},
        )
        with (
            patch("handspread.market.finnhub_client._get_client", return_value=client),
            patch("handspread.market.finnhub_client.get_settings", return_value=_mock_settings()),
        ):
            snap = await fetch_market_snapshot("TSM")

        # Should use vendor market cap (950000M = $950B), NOT 200 * 25.9B = $5.18T
        assert snap.market_cap.value == 950_000_000_000
        assert isinstance(snap.market_cap, MarketValue)
        assert snap.market_cap.endpoint == "profile"

    @pytest.mark.asyncio
    async def test_vendor_market_cap_missing_falls_back(self):
        """Profile omits marketCapitalization; verify fallback to price * shares."""
        client = _mock_client(
            profile={"shareOutstanding": 24.3, "name": "Test Corp"},
        )
        with (
            patch("handspread.market.finnhub_client._get_client", return_value=client),
            patch("handspread.market.finnhub_client.get_settings", return_value=_mock_settings()),
        ):
            snap = await fetch_market_snapshot("TEST")

        expected_mcap = 150.0 * 24_300_000
        assert snap.market_cap.value == expected_mcap
        assert isinstance(snap.market_cap, ComputedValue)

    @pytest.mark.asyncio
    async def test_vendor_market_cap_zero_falls_back(self):
        """Profile returns marketCapitalization=0; should fall back to computed."""
        client = _mock_client(
            profile={
                "shareOutstanding": 10.0,
                "marketCapitalization": 0,
                "name": "Zero MCap Corp",
            },
        )
        with (
            patch("handspread.market.finnhub_client._get_client", return_value=client),
            patch("handspread.market.finnhub_client.get_settings", return_value=_mock_settings()),
        ):
            snap = await fetch_market_snapshot("ZERO_MCAP")

        assert isinstance(snap.market_cap, ComputedValue)
        expected_mcap = 150.0 * 10_000_000
        assert snap.market_cap.value == expected_mcap


class TestVendorMcapCurrencyCrossCheck:
    """Vendor market cap should be rejected when profile currency is non-USD and value diverges."""

    @pytest.mark.asyncio
    async def test_non_usd_currency_high_ratio_falls_back(self):
        """TSM-like: currency=TWD, vendor mcap is 5x computed -> fall back to computed."""
        client = _mock_client(
            profile={
                "shareOutstanding": 25900.0,  # 25.9B shares (ordinary)
                "marketCapitalization": 49000000,  # 49T TWD in millions
                "name": "TSM Corp",
                "currency": "TWD",
            },
            quote={"c": 200.0, "t": 1700000000},
        )
        with (
            patch("handspread.market.finnhub_client._get_client", return_value=client),
            patch("handspread.market.finnhub_client.get_settings", return_value=_mock_settings()),
        ):
            snap = await fetch_market_snapshot("TSM")

        # Should fall back to computed (price * shares) because vendor is in TWD
        assert isinstance(snap.market_cap, ComputedValue)
        expected = 200.0 * 25_900_000_000
        assert snap.market_cap.value == expected
        # Warning should mention non-USD denomination on the market_cap ComputedValue
        assert any("non-USD" in w for w in snap.market_cap.warnings)

    @pytest.mark.asyncio
    async def test_non_usd_currency_reasonable_ratio_uses_vendor(self):
        """BABA-like: currency=CNY, but vendor mcap is reasonable in USD -> use vendor."""
        client = _mock_client(
            profile={
                "shareOutstanding": 2500.0,  # 2.5B shares
                "marketCapitalization": 334000,  # $334B in millions
                "name": "BABA Corp",
                "currency": "CNY",
            },
            quote={"c": 130.0, "t": 1700000000},
        )
        with (
            patch("handspread.market.finnhub_client._get_client", return_value=client),
            patch("handspread.market.finnhub_client.get_settings", return_value=_mock_settings()),
        ):
            snap = await fetch_market_snapshot("BABA")

        # Vendor mcap = 334B, computed = 130 * 2.5B = 325B, ratio ~1.03 -> use vendor
        assert isinstance(snap.market_cap, MarketValue)
        assert snap.market_cap.value == 334_000_000_000

    @pytest.mark.asyncio
    async def test_usd_currency_any_ratio_uses_vendor(self):
        """USD profile should always use vendor regardless of ratio."""
        client = _mock_client(
            profile={
                "shareOutstanding": 100.0,
                "marketCapitalization": 500000,
                "name": "USD Corp",
                "currency": "USD",
            },
            quote={"c": 100.0, "t": 1700000000},
        )
        with (
            patch("handspread.market.finnhub_client._get_client", return_value=client),
            patch("handspread.market.finnhub_client.get_settings", return_value=_mock_settings()),
        ):
            snap = await fetch_market_snapshot("TEST")

        assert isinstance(snap.market_cap, MarketValue)
        assert snap.market_cap.value == 500_000_000_000

    @pytest.mark.asyncio
    async def test_missing_currency_treated_as_usd(self):
        """Profile without currency field should default to USD behavior."""
        client = _mock_client(
            profile={
                "shareOutstanding": 100.0,
                "marketCapitalization": 500000,
                "name": "NoCurrency Corp",
            },
            quote={"c": 100.0, "t": 1700000000},
        )
        with (
            patch("handspread.market.finnhub_client._get_client", return_value=client),
            patch("handspread.market.finnhub_client.get_settings", return_value=_mock_settings()),
        ):
            snap = await fetch_market_snapshot("TEST")

        assert isinstance(snap.market_cap, MarketValue)
        assert snap.market_cap.value == 500_000_000_000


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
