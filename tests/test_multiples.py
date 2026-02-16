"""Tests for valuation multiples computation."""

from datetime import UTC, datetime
from types import SimpleNamespace

from handspread.analysis.multiples import compute_multiples
from handspread.models import ComputedValue, EVBridge, MarketSnapshot, MarketValue


def _cited(value, metric="test"):
    """Stub CitedValue via SimpleNamespace (only .value is read by multiples)."""
    return SimpleNamespace(value=value, metric=metric)


def _make_ev_bridge(ev_value):
    return EVBridge(
        enterprise_value=ComputedValue(
            metric="enterprise_value",
            value=ev_value,
            unit="USD",
            formula="equity_value + debt - cash",
        )
    )


def _make_snapshot(price=100.0, shares=1_000_000):
    now = datetime(2025, 1, 15, 12, 0, tzinfo=UTC)
    p = MarketValue(
        metric="price",
        value=price,
        unit="USD",
        vendor="finnhub",
        symbol="TEST",
        endpoint="quote",
        fetched_at=now,
    )
    s = MarketValue(
        metric="shares_outstanding",
        value=shares,
        unit="shares",
        vendor="finnhub",
        symbol="TEST",
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
        symbol="TEST",
        company_name="Test Corp",
        price=p,
        shares_outstanding=s,
        market_cap=mcap,
    )


class TestEVMultiples:
    def test_ev_revenue(self):
        bridge = _make_ev_bridge(10_000_000_000)
        market = _make_snapshot()
        sec = {"revenue": _cited(2_000_000_000)}

        result = compute_multiples(bridge, market, sec)
        assert abs(result["ev_revenue"].value - 5.0) < 0.001

    def test_ev_ebitda(self):
        bridge = _make_ev_bridge(10_000_000_000)
        market = _make_snapshot()
        sec = {"ebitda": _cited(1_000_000_000)}

        result = compute_multiples(bridge, market, sec)
        assert abs(result["ev_ebitda"].value - 10.0) < 0.001

    def test_none_denominator(self):
        bridge = _make_ev_bridge(10_000_000_000)
        market = _make_snapshot()
        sec = {}

        result = compute_multiples(bridge, market, sec)
        assert result["ev_revenue"].value is None
        assert any("Denominator unavailable" in w for w in result["ev_revenue"].warnings)

    def test_zero_denominator(self):
        bridge = _make_ev_bridge(10_000_000_000)
        market = _make_snapshot()
        sec = {"revenue": _cited(0)}

        result = compute_multiples(bridge, market, sec)
        assert result["ev_revenue"].value is None
        assert any("zero" in w for w in result["ev_revenue"].warnings)


class TestEquityMultiples:
    def test_pe_ratio(self):
        bridge = _make_ev_bridge(10_000_000_000)
        market = _make_snapshot(price=100.0, shares=1_000_000)
        sec = {"net_income": _cited(5_000_000)}

        result = compute_multiples(bridge, market, sec)
        expected = 100_000_000 / 5_000_000  # 20x
        assert abs(result["pe"].value - expected) < 0.001

    def test_fcf_yield(self):
        bridge = _make_ev_bridge(10_000_000_000)
        market = _make_snapshot(price=100.0, shares=1_000_000)
        sec = {"free_cash_flow": _cited(10_000_000)}

        result = compute_multiples(bridge, market, sec)
        expected = 10_000_000 / 100_000_000  # 0.1
        assert abs(result["fcf_yield"].value - expected) < 0.001

    def test_dividend_yield(self):
        bridge = _make_ev_bridge(10_000_000_000)
        market = _make_snapshot(price=50.0, shares=1_000_000)
        sec = {"dividends_per_share": _cited(2.0)}

        result = compute_multiples(bridge, market, sec)
        expected = 2.0 / 50.0  # 0.04
        assert abs(result["dividend_yield"].value - expected) < 0.001


class TestNegativeNetIncomePE:
    def test_negative_net_income_pe(self):
        """Negative NI produces a negative P/E with warning about negative denominator."""
        bridge = _make_ev_bridge(10_000_000_000)
        market = _make_snapshot(price=100.0, shares=1_000_000)
        sec = {"net_income": _cited(-5_000_000)}

        result = compute_multiples(bridge, market, sec)
        # mcap = 100M, NI = -5M, P/E = -20x
        assert result["pe"].value is not None
        assert result["pe"].value < 0
        assert any("Negative denominator" in w for w in result["pe"].warnings)


class TestNoneEVProducesNoneMultiples:
    def test_none_ev_produces_none_multiples(self):
        """EVBridge with None EV produces None for all EV-based multiples."""
        bridge = _make_ev_bridge(None)
        market = _make_snapshot(price=100.0, shares=1_000_000)
        sec = {"revenue": _cited(1_000_000)}

        result = compute_multiples(bridge, market, sec)
        assert result["ev_revenue"].value is None
        assert result["ev_ebitda"].value is None
        assert any("Numerator unavailable" in w for w in result["ev_revenue"].warnings)
