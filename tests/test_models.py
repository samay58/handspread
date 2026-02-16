"""Tests for core data models."""

from datetime import UTC, datetime

from handspread.models import ComputedValue, MarketSnapshot, MarketValue


def _make_market_value(**overrides):
    defaults = {
        "metric": "price",
        "value": 100.0,
        "unit": "USD",
        "vendor": "finnhub",
        "symbol": "TEST",
        "endpoint": "quote",
        "fetched_at": datetime(2025, 1, 15, 12, 0, tzinfo=UTC),
    }
    defaults.update(overrides)
    return MarketValue(**defaults)


class TestMarketValue:
    def test_citation_format(self):
        mv = _make_market_value()
        assert "finnhub:quote" in mv.citation
        assert "TEST" in mv.citation
        assert "2025-01-15" in mv.citation

    def test_none_value(self):
        mv = _make_market_value(value=None)
        assert mv.value is None
        assert mv.citation  # still produces a citation


class TestComputedValue:
    def test_formula_recorded(self):
        cv = ComputedValue(
            metric="market_cap",
            value=1_000_000,
            unit="USD",
            formula="price * shares_outstanding",
        )
        assert cv.formula == "price * shares_outstanding"
        assert cv.value == 1_000_000

    def test_none_value_with_formula(self):
        cv = ComputedValue(
            metric="ev_revenue",
            value=None,
            unit="x",
            formula="enterprise_value / revenue",
            warnings=["Numerator unavailable"],
        )
        assert cv.value is None
        assert len(cv.warnings) == 1


class TestMarketSnapshot:
    def test_market_cap_computation(self):
        price = _make_market_value(metric="price", value=150.0)
        shares = _make_market_value(metric="shares_outstanding", value=1_000_000, unit="shares")
        mcap = ComputedValue(
            metric="market_cap",
            value=150.0 * 1_000_000,
            unit="USD",
            formula="price * shares_outstanding",
            components={"price": price, "shares_outstanding": shares},
        )
        snap = MarketSnapshot(
            symbol="TEST",
            company_name="Test Corp",
            price=price,
            shares_outstanding=shares,
            market_cap=mcap,
        )
        assert snap.market_cap_value == 150_000_000

    def test_market_cap_none_when_price_missing(self):
        price = _make_market_value(metric="price", value=None)
        shares = _make_market_value(metric="shares_outstanding", value=1_000_000, unit="shares")
        mcap = ComputedValue(
            metric="market_cap",
            value=None,
            unit="USD",
            formula="price * shares_outstanding",
        )
        snap = MarketSnapshot(
            symbol="TEST",
            company_name="Test Corp",
            price=price,
            shares_outstanding=shares,
            market_cap=mcap,
        )
        assert snap.market_cap_value is None
