"""Tests for enterprise value bridge construction."""

from datetime import datetime, timezone
from types import SimpleNamespace

from handspread.analysis.enterprise_value import build_ev_bridge
from handspread.models import ComputedValue, EVPolicy, MarketSnapshot, MarketValue


def _cited(value, metric="test", unit="USD"):
    """Stub that mimics CitedValue with .value attribute."""
    return SimpleNamespace(value=value, metric=metric, unit=unit)


def _make_snapshot(price=100.0, shares=1_000_000):
    now = datetime(2025, 1, 15, 12, 0, tzinfo=timezone.utc)
    p = MarketValue(
        metric="price", value=price, unit="USD",
        vendor="finnhub", symbol="TEST", endpoint="quote", fetched_at=now,
    )
    s = MarketValue(
        metric="shares_outstanding", value=shares, unit="shares",
        vendor="finnhub", symbol="TEST", endpoint="profile", fetched_at=now,
    )
    mcap_val = price * shares if price and shares else None
    mcap = ComputedValue(
        metric="market_cap", value=mcap_val, unit="USD",
        formula="price * shares_outstanding",
        components={"price": p, "shares_outstanding": s},
    )
    return MarketSnapshot(
        symbol="TEST", company_name="Test Corp",
        price=p, shares_outstanding=s, market_cap=mcap,
    )


class TestBaseEV:
    def test_simple_ev(self):
        """EV = market_cap + total_debt - cash."""
        market = _make_snapshot(price=100.0, shares=1_000_000)
        sec = {
            "total_debt": _cited(500_000),
            "cash": _cited(200_000),
        }
        bridge = build_ev_bridge(market, sec)

        expected = 100_000_000 + 500_000 - 200_000
        assert bridge.enterprise_value is not None
        assert bridge.enterprise_value.value == expected

    def test_missing_debt_treated_as_zero(self):
        """Missing debt should produce EV = market_cap - cash with warning."""
        market = _make_snapshot(price=50.0, shares=2_000_000)
        sec = {"cash": _cited(1_000_000)}
        bridge = build_ev_bridge(market, sec)

        expected = 100_000_000 - 1_000_000
        assert bridge.enterprise_value.value == expected
        assert any("total_debt missing" in w for w in bridge.enterprise_value.warnings)

    def test_missing_cash_treated_as_zero(self):
        market = _make_snapshot(price=50.0, shares=2_000_000)
        sec = {"total_debt": _cited(5_000_000)}
        bridge = build_ev_bridge(market, sec)

        expected = 100_000_000 + 5_000_000
        assert bridge.enterprise_value.value == expected
        assert any("cash missing" in w for w in bridge.enterprise_value.warnings)


class TestLeaseIncluded:
    def test_includes_lease_liabilities(self):
        market = _make_snapshot(price=100.0, shares=1_000_000)
        sec = {
            "total_debt": _cited(500_000),
            "cash": _cited(200_000),
            "operating_lease_liabilities": _cited(300_000),
        }
        policy = EVPolicy(include_leases=True)
        bridge = build_ev_bridge(market, sec, policy)

        expected = 100_000_000 + 500_000 - 200_000 + 300_000
        assert bridge.enterprise_value.value == expected

    def test_lease_missing_produces_warning(self):
        market = _make_snapshot(price=100.0, shares=1_000_000)
        sec = {"total_debt": _cited(500_000), "cash": _cited(200_000)}
        policy = EVPolicy(include_leases=True)
        bridge = build_ev_bridge(market, sec, policy)

        assert any(
            "operating_lease_liabilities" in w
            for w in bridge.enterprise_value.warnings
        )


class TestDebtOverlap:
    def test_split_mode_warns_overlap(self):
        market = _make_snapshot(price=100.0, shares=1_000_000)
        sec = {
            "total_debt": _cited(500_000),
            "short_term_debt": _cited(100_000),
            "cash": _cited(200_000),
        }
        policy = EVPolicy(debt_mode="split")
        bridge = build_ev_bridge(market, sec, policy)

        assert any("overlap" in w for w in bridge.enterprise_value.warnings)

    def test_total_only_ignores_short_term(self):
        market = _make_snapshot(price=100.0, shares=1_000_000)
        sec = {
            "total_debt": _cited(500_000),
            "short_term_debt": _cited(100_000),
            "cash": _cited(0),
        }
        policy = EVPolicy(debt_mode="total_only")
        bridge = build_ev_bridge(market, sec, policy)

        # Short-term debt should not be added
        expected = 100_000_000 + 500_000
        assert bridge.enterprise_value.value == expected


class TestMissingMarketCap:
    def test_none_ev_when_no_market_cap(self):
        market = _make_snapshot(price=None, shares=1_000_000)
        sec = {"total_debt": _cited(500_000), "cash": _cited(200_000)}
        bridge = build_ev_bridge(market, sec)

        assert bridge.enterprise_value is not None
        assert bridge.enterprise_value.value is None
        assert any("Market cap" in w for w in bridge.enterprise_value.warnings)
