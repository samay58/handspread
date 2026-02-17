"""Tests for operating efficiency metrics."""

from datetime import UTC, datetime
from types import SimpleNamespace

from handspread.analysis.operating import compute_operating
from handspread.models import ComputedValue, MarketSnapshot, MarketValue


def _cited(value, metric="test", unit=None):
    """Stub CitedValue via SimpleNamespace (only .value is read by operating)."""
    return SimpleNamespace(value=value, metric=metric, unit=unit)


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
    mcap = ComputedValue(
        metric="market_cap",
        value=price * shares,
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


class TestPercentOfRevenue:
    def test_rd_pct_revenue(self):
        sec = {"revenue": _cited(1_000_000), "rd_expense": _cited(150_000)}
        result = compute_operating(sec)
        assert abs(result["rd_pct_revenue"].value - 0.15) < 0.001

    def test_sga_pct_revenue(self):
        sec = {"revenue": _cited(1_000_000), "sga_expense": _cited(200_000)}
        result = compute_operating(sec)
        assert abs(result["sga_pct_revenue"].value - 0.20) < 0.001

    def test_capex_pct_revenue(self):
        sec = {"revenue": _cited(1_000_000), "capex": _cited(100_000)}
        result = compute_operating(sec)
        assert abs(result["capex_pct_revenue"].value - 0.10) < 0.001

    def test_missing_revenue_skips(self):
        sec = {"rd_expense": _cited(150_000)}
        result = compute_operating(sec)
        assert "rd_pct_revenue" not in result


class TestRevenuePerShare:
    def test_basic(self):
        sec = {"revenue": _cited(10_000_000)}
        market = _make_snapshot(shares=1_000_000)
        result = compute_operating(sec, market)

        assert abs(result["revenue_per_share"].value - 10.0) < 0.001

    def test_no_market_skips(self):
        sec = {"revenue": _cited(10_000_000)}
        result = compute_operating(sec, None)
        assert "revenue_per_share" not in result

    def test_revenue_per_share_uses_sec_currency_unit(self):
        sec = {"revenue": _cited(10_000_000, unit="JPY")}
        market = _make_snapshot(shares=1_000_000)
        result = compute_operating(sec, market)

        assert result["revenue_per_share"].unit == "JPY/shares"
        assert any("cannot mix currencies" in w for w in result["revenue_per_share"].warnings)


class TestROIC:
    def test_basic_roic(self):
        sec = {
            "revenue": _cited(10_000_000),
            "operating_income": _cited(2_000_000),
            "total_debt": _cited(3_000_000),
            "stockholders_equity": _cited(7_000_000),
        }
        result = compute_operating(sec)

        # NOPAT = 2M * (1 - 0.21) = 1.58M
        # Invested capital = 3M + 7M = 10M
        # ROIC = 0.158
        expected = 2_000_000 * 0.79 / 10_000_000
        assert abs(result["roic"].value - expected) < 0.001
        assert any("21.0% tax rate" in w for w in result["roic"].warnings)

    def test_missing_equity_skips_roic(self):
        sec = {
            "revenue": _cited(10_000_000),
            "operating_income": _cited(2_000_000),
            "total_debt": _cited(3_000_000),
        }
        result = compute_operating(sec)
        assert "roic" not in result


class TestZeroInvestedCapital:
    def test_zero_invested_capital_skips_roic(self):
        """invested_capital = 0 should skip ROIC to avoid division by zero."""
        sec = {
            "revenue": _cited(10_000_000),
            "operating_income": _cited(2_000_000),
            "total_debt": _cited(0),
            "stockholders_equity": _cited(0),
        }
        result = compute_operating(sec)
        assert "roic" not in result


class TestZeroSharesSkipsRevenuePerShare:
    def test_zero_shares_skips_revenue_per_share(self):
        """shares = 0 should skip revenue_per_share."""
        sec = {"revenue": _cited(10_000_000)}
        market = _make_snapshot(price=100.0, shares=0)
        result = compute_operating(sec, market)
        assert "revenue_per_share" not in result


class TestNegativeOperatingIncomeROIC:
    def test_negative_operating_income_produces_negative_roic(self):
        sec = {
            "operating_income": _cited(-2_000_000),
            "total_debt": _cited(3_000_000),
            "stockholders_equity": _cited(7_000_000),
        }
        result = compute_operating(sec)

        assert result["roic"].value is not None
        assert result["roic"].value < 0
