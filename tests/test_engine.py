"""Tests for the engine orchestrator (analyze_comps + _build_single)."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from edgarpack.query.models import QueryResult

from handspread.engine import analyze_comps
from handspread.models import ComputedValue, MarketSnapshot, MarketValue


def _make_snapshot(symbol="TEST", company_name="Test Corp", price=100.0, shares=1_000_000):
    """Build a minimal MarketSnapshot for testing the orchestrator."""
    now = datetime(2025, 1, 15, 12, 0, tzinfo=UTC)
    p = MarketValue(
        metric="price",
        value=price,
        unit="USD",
        vendor="finnhub",
        symbol=symbol,
        endpoint="quote",
        fetched_at=now,
    )
    s = MarketValue(
        metric="shares_outstanding",
        value=shares,
        unit="shares",
        vendor="finnhub",
        symbol=symbol,
        endpoint="profile",
        fetched_at=now,
    )
    mcap_val = price * shares if price and shares else None
    mcap = ComputedValue(
        metric="market_cap",
        value=mcap_val,
        unit="USD",
        formula="price * shares_outstanding",
    )
    return MarketSnapshot(
        symbol=symbol,
        company_name=company_name,
        price=p,
        shares_outstanding=s,
        market_cap=mcap,
    )


def _make_query_result(ticker, company="Test Corp", cik="0001234"):
    """Build a QueryResult with SimpleNamespace CitedValue stubs.

    Uses model_construct to bypass Pydantic validation since analysis modules
    only read .value from metric objects, not the full CitedValue schema.
    """
    return QueryResult.model_construct(
        company=company,
        cik=cik,
        period="ltm",
        metrics={
            "revenue": SimpleNamespace(value=1_000_000),
            "net_income": SimpleNamespace(value=200_000),
            "ebitda": SimpleNamespace(value=300_000),
            "operating_income": SimpleNamespace(value=250_000),
            "total_debt": SimpleNamespace(value=500_000),
            "cash": SimpleNamespace(value=100_000),
            "stockholders_equity": SimpleNamespace(value=800_000),
            "free_cash_flow": SimpleNamespace(value=150_000),
        },
    )


SEC_PATCH = "handspread.engine.comps"
MARKET_PATCH = "handspread.engine.fetch_market_snapshots"


class TestAllStreamsFail:
    @pytest.mark.asyncio
    async def test_all_streams_fail(self):
        """When all three data streams raise, CompanyAnalysis has errors but no crash."""
        with (
            patch(SEC_PATCH, new_callable=AsyncMock, side_effect=RuntimeError("SEC down")),
            patch(MARKET_PATCH, new_callable=AsyncMock, side_effect=RuntimeError("down")),
        ):
            results = await analyze_comps(["NVDA"])

        assert len(results) == 1
        r = results[0]
        assert r.symbol == "NVDA"
        assert any("SEC" in e for e in r.errors)
        assert any("Market" in e for e in r.errors)
        assert r.ev_bridge is None
        assert r.multiples == {}


class TestSecOnlyFail:
    @pytest.mark.asyncio
    async def test_sec_only_fail(self):
        """Market works, SEC fails. Partial analysis with market data + error."""
        snapshot = _make_snapshot(symbol="NVDA", company_name="NVIDIA Corporation")
        with (
            patch(SEC_PATCH, new_callable=AsyncMock, side_effect=RuntimeError("SEC down")),
            patch(MARKET_PATCH, new_callable=AsyncMock, return_value={"NVDA": snapshot}),
        ):
            results = await analyze_comps(["NVDA"])

        r = results[0]
        assert r.market is not None
        assert r.market.price.value == 100.0
        assert any("SEC" in e for e in r.errors)
        assert r.company_name == "NVIDIA Corporation"


class TestMarketOnlyFail:
    @pytest.mark.asyncio
    async def test_market_only_fail(self):
        """SEC works, market fails. SEC data present, no EV bridge."""
        qr = _make_query_result("NVDA", company="NVIDIA Corp", cik="0001045810")
        with (
            patch(SEC_PATCH, new_callable=AsyncMock, return_value={"NVDA": qr}),
            patch(MARKET_PATCH, new_callable=AsyncMock, side_effect=RuntimeError("Market down")),
        ):
            results = await analyze_comps(["NVDA"])

        r = results[0]
        assert r.company_name == "NVIDIA Corp"
        assert r.cik == "0001045810"
        assert r.ev_bridge is None
        assert any("Market" in e for e in r.errors)


class TestBuildSinglePopulatesName:
    @pytest.mark.asyncio
    async def test_name_from_sec_takes_priority(self):
        """Company name resolution: SEC name > market name > ticker fallback."""
        qr = _make_query_result("NVDA", company="NVIDIA Corporation", cik="0001045810")
        snapshot = _make_snapshot(symbol="NVDA", company_name="NVIDIA Corp")
        with (
            patch(SEC_PATCH, new_callable=AsyncMock, return_value={"NVDA": qr}),
            patch(MARKET_PATCH, new_callable=AsyncMock, return_value={"NVDA": snapshot}),
        ):
            results = await analyze_comps(["NVDA"])

        # SEC name takes priority over market name
        assert results[0].company_name == "NVIDIA Corporation"

    @pytest.mark.asyncio
    async def test_name_falls_back_to_market(self):
        """When SEC result is None, uses market company_name."""
        snapshot = _make_snapshot(symbol="NVDA", company_name="NVIDIA Corp")
        with (
            patch(SEC_PATCH, new_callable=AsyncMock, return_value={}),
            patch(MARKET_PATCH, new_callable=AsyncMock, return_value={"NVDA": snapshot}),
        ):
            results = await analyze_comps(["NVDA"])

        assert results[0].company_name == "NVIDIA Corp"


class TestValuationTimestamp:
    @pytest.mark.asyncio
    async def test_valuation_timestamp_set(self):
        """Verify valuation_timestamp is set to roughly now (UTC)."""
        qr = _make_query_result("NVDA")
        snapshot = _make_snapshot(symbol="NVDA")
        with (
            patch(SEC_PATCH, new_callable=AsyncMock, return_value={"NVDA": qr}),
            patch(MARKET_PATCH, new_callable=AsyncMock, return_value={"NVDA": snapshot}),
        ):
            before = datetime.now(UTC)
            results = await analyze_comps(["NVDA"])
            after = datetime.now(UTC)

        ts = results[0].valuation_timestamp
        assert ts is not None
        assert before <= ts <= after


class TestTimeoutHandling:
    @pytest.mark.asyncio
    async def test_timeout_returns_per_company_errors(self):
        """Timeout should return per-company results with SEC and market errors."""
        with patch("handspread.engine.asyncio.wait_for", side_effect=TimeoutError):
            results = await analyze_comps(["NVDA"], timeout=0.001)

        assert len(results) == 1
        r = results[0]
        assert r.symbol == "NVDA"
        assert any("SEC" in e for e in r.errors)
        assert any("Market" in e for e in r.errors)


class TestInputValidation:
    @pytest.mark.asyncio
    async def test_empty_tickers_raises(self):
        with pytest.raises(ValueError, match="at least one symbol"):
            await analyze_comps([])
