"""Tests for valuation multiples computation."""

from datetime import UTC, datetime
from types import SimpleNamespace

from handspread.analysis._utils import compute_adjusted_ebitda
from handspread.analysis.multiples import compute_multiples
from handspread.models import ComputedValue, EVBridge, MarketSnapshot, MarketValue


def _cited(value, metric="test", unit=None):
    """Stub CitedValue via SimpleNamespace (only .value is read by multiples)."""
    return SimpleNamespace(value=value, metric=metric, unit=unit)


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

    def test_ev_ebitda_gaap(self):
        """GAAP EV/EBITDA uses the raw ebitda value."""
        bridge = _make_ev_bridge(10_000_000_000)
        market = _make_snapshot()
        sec = {"ebitda": _cited(1_000_000_000)}

        result = compute_multiples(bridge, market, sec)
        assert abs(result["ev_ebitda_gaap"].value - 10.0) < 0.001

    def test_ev_ebitda_adjusted(self):
        """EV/EBITDA (adjusted) = EV / (OI + D&A + SBC)."""
        bridge = _make_ev_bridge(10_000_000_000)
        market = _make_snapshot()
        sec = {
            "operating_income": _cited(600_000_000),
            "depreciation_amortization": _cited(200_000_000),
            "stock_based_compensation": _cited(200_000_000),
        }

        result = compute_multiples(bridge, market, sec)
        # adjusted EBITDA = 600M + 200M + 200M = 1B
        assert abs(result["ev_ebitda"].value - 10.0) < 0.001

    def test_ev_ebitda_adjusted_no_sbc_falls_back_to_gaap(self):
        """Missing SBC means adjusted EBITDA = OI + D&A (equals GAAP EBITDA)."""
        bridge = _make_ev_bridge(10_000_000_000)
        market = _make_snapshot()
        sec = {
            "operating_income": _cited(800_000_000),
            "depreciation_amortization": _cited(200_000_000),
        }

        result = compute_multiples(bridge, market, sec)
        # adjusted EBITDA = 800M + 200M + 0 = 1B
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


class TestAdjustedEBITDA:
    def test_full_computation(self):
        """OI + D&A + SBC = adjusted EBITDA."""
        sec = {
            "operating_income": _cited(500),
            "depreciation_amortization": _cited(100),
            "stock_based_compensation": _cited(50),
        }
        val, cv, warnings = compute_adjusted_ebitda(sec)
        assert val == 650
        assert cv.value == 650
        assert cv.metric == "adjusted_ebitda"
        assert warnings == []

    def test_missing_sbc_warns(self):
        """Missing SBC adds warning; adjusted EBITDA = OI + D&A."""
        sec = {
            "operating_income": _cited(500),
            "depreciation_amortization": _cited(100),
        }
        val, cv, warnings = compute_adjusted_ebitda(sec)
        assert val == 600
        assert any("SBC unavailable" in w for w in warnings)

    def test_missing_oi_returns_none(self):
        sec = {
            "depreciation_amortization": _cited(100),
            "stock_based_compensation": _cited(50),
        }
        val, cv, warnings = compute_adjusted_ebitda(sec)
        assert val is None
        assert cv is None

    def test_missing_da_returns_none(self):
        sec = {
            "operating_income": _cited(500),
            "stock_based_compensation": _cited(50),
        }
        val, cv, warnings = compute_adjusted_ebitda(sec)
        assert val is None
        assert cv is None

    def test_components_tracked(self):
        sec = {
            "operating_income": _cited(500),
            "depreciation_amortization": _cited(100),
            "stock_based_compensation": _cited(50),
        }
        _, cv, _ = compute_adjusted_ebitda(sec)
        assert "operating_income" in cv.components
        assert "depreciation_amortization" in cv.components
        assert "stock_based_compensation" in cv.components

    def test_adjusted_ebitda_in_result_dict(self):
        """compute_multiples should emit adjusted_ebitda as a standalone entry."""
        bridge = _make_ev_bridge(10_000_000_000)
        market = _make_snapshot()
        sec = {
            "operating_income": _cited(600_000_000),
            "depreciation_amortization": _cited(200_000_000),
            "stock_based_compensation": _cited(200_000_000),
        }
        result = compute_multiples(bridge, market, sec)
        assert "adjusted_ebitda" in result
        assert result["adjusted_ebitda"].value == 1_000_000_000
        assert result["adjusted_ebitda"].metric == "adjusted_ebitda"

    def test_adjusted_ebitda_absent_when_missing_components(self):
        """If OI or D&A is missing, adjusted_ebitda should not appear in result."""
        bridge = _make_ev_bridge(10_000_000_000)
        market = _make_snapshot()
        sec = {"revenue": _cited(2_000_000_000)}
        result = compute_multiples(bridge, market, sec)
        assert "adjusted_ebitda" not in result


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
        assert result["fcf_yield"].unit == "pure"

    def test_dividend_yield(self):
        bridge = _make_ev_bridge(10_000_000_000)
        market = _make_snapshot(price=50.0, shares=1_000_000)
        sec = {"dividends_per_share": _cited(2.0)}

        result = compute_multiples(bridge, market, sec)
        expected = 2.0 / 50.0  # 0.04
        assert abs(result["dividend_yield"].value - expected) < 0.001
        assert result["dividend_yield"].unit == "pure"


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


class TestCurrencyMismatch:
    def test_non_usd_sec_data_blocks_market_cross_metrics(self):
        bridge = _make_ev_bridge(10_000_000_000)
        market = _make_snapshot(price=100.0, shares=1_000_000)
        sec = {
            "revenue": _cited(2_000_000_000, unit="JPY"),
            "ebitda": _cited(1_000_000_000, unit="JPY"),
            "operating_income": _cited(800_000_000, unit="JPY"),
            "free_cash_flow": _cited(700_000_000, unit="JPY"),
            "net_income": _cited(600_000_000, unit="JPY"),
            "stockholders_equity": _cited(4_000_000_000, unit="JPY"),
            "dividends_per_share": _cited(100, unit="JPY/shares"),
        }

        result = compute_multiples(bridge, market, sec)

        for metric in (
            "ev_revenue",
            "ev_ebitda",
            "ev_ebit",
            "ev_fcf",
            "pe",
            "price_book",
            "fcf_yield",
            "dividend_yield",
        ):
            assert result[metric].value is None
            assert any("cannot mix currencies" in w for w in result[metric].warnings)
