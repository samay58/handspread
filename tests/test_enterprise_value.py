"""Tests for enterprise value bridge construction."""

from datetime import UTC, datetime
from types import SimpleNamespace

from handspread.analysis.enterprise_value import build_ev_bridge
from handspread.models import ComputedValue, EVPolicy, MarketSnapshot, MarketValue


def _cited(value, metric="test", unit="USD"):
    """Stub CitedValue with .value attribute. Uses SimpleNamespace (no full provenance needed)."""
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
    mcap_val = price * shares if price and shares else None
    mcap = ComputedValue(
        metric="market_cap",
        value=mcap_val,
        unit="USD",
        formula="price * shares_outstanding",
        components={"price": p, "shares_outstanding": s},
    )
    return MarketSnapshot(
        symbol="TEST",
        company_name="Test Corp",
        price=p,
        shares_outstanding=s,
        market_cap=mcap,
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

        assert any("operating_lease_liabilities" in w for w in bridge.enterprise_value.warnings)


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


class TestCashTreatmentIgnore:
    def test_cash_treatment_ignore(self):
        """Policy with cash_treatment='ignore' means cash is not subtracted from EV."""
        market = _make_snapshot(price=100.0, shares=1_000_000)
        sec = {
            "total_debt": _cited(500_000),
            "cash": _cited(200_000),
            "marketable_securities": _cited(50_000),
        }
        policy = EVPolicy(cash_treatment="ignore")
        bridge = build_ev_bridge(market, sec, policy)

        # EV = market_cap + debt (no cash subtraction)
        expected = 100_000_000 + 500_000
        assert bridge.enterprise_value.value == expected
        assert bridge.cash_and_equivalents is None
        assert bridge.marketable_securities is None


class TestEquityMethodInvestments:
    def test_equity_method_investments_subtracted(self):
        """Policy flag on: EMI subtracted from EV."""
        market = _make_snapshot(price=100.0, shares=1_000_000)
        sec = {
            "total_debt": _cited(500_000),
            "cash": _cited(200_000),
            "equity_method_investments": _cited(100_000),
        }
        policy = EVPolicy(subtract_equity_method_investments=True)
        bridge = build_ev_bridge(market, sec, policy)

        expected = 100_000_000 + 500_000 - 200_000 - 100_000
        assert bridge.enterprise_value.value == expected
        assert bridge.equity_method_investments is not None


class TestCombinedAdjustments:
    def test_leases_preferred_nci_all_present(self):
        """All optional adjustments: leases + preferred + NCI."""
        market = _make_snapshot(price=100.0, shares=1_000_000)
        sec = {
            "total_debt": _cited(500_000),
            "cash": _cited(200_000),
            "operating_lease_liabilities": _cited(300_000),
            "preferred_stock": _cited(50_000),
            "noncontrolling_interests": _cited(25_000),
        }
        policy = EVPolicy(include_leases=True)
        bridge = build_ev_bridge(market, sec, policy)

        expected = 100_000_000 + 500_000 - 200_000 + 300_000 + 50_000 + 25_000
        assert bridge.enterprise_value.value == expected


class TestNetDebt:
    def test_net_debt_computed_correctly(self):
        """Verify net_debt = total_debt - cash - marketable_securities."""
        market = _make_snapshot(price=100.0, shares=1_000_000)
        sec = {
            "total_debt": _cited(800_000),
            "cash": _cited(200_000),
            "marketable_securities": _cited(100_000),
        }
        bridge = build_ev_bridge(market, sec)

        assert bridge.net_debt is not None
        # net_debt = 800K - 200K - 100K = 500K
        assert bridge.net_debt.value == 500_000


class TestCurrencyMismatch:
    def test_currency_mismatch_returns_none_ev(self):
        """Non-USD SEC data should produce None EV with currency warning."""
        market = _make_snapshot(price=100.0, shares=1_000_000)
        sec = {
            "total_debt": _cited(4_000_000_000_000, unit="JPY"),
            "cash": _cited(500_000_000_000, unit="JPY"),
        }
        bridge = build_ev_bridge(market, sec)

        assert bridge.enterprise_value is not None
        assert bridge.enterprise_value.value is None
        assert any("JPY" in w for w in bridge.enterprise_value.warnings)
        # Equity value should still be set
        assert bridge.equity_value is not None
        assert bridge.equity_value.value == 100_000_000

    def test_usd_sec_data_computes_normally(self):
        """USD SEC data should compute EV normally (no regression)."""
        market = _make_snapshot(price=100.0, shares=1_000_000)
        sec = {
            "total_debt": _cited(500_000, unit="USD"),
            "cash": _cited(200_000, unit="USD"),
        }
        bridge = build_ev_bridge(market, sec)

        expected = 100_000_000 + 500_000 - 200_000
        assert bridge.enterprise_value.value == expected


class TestMissingMarketCap:
    def test_none_ev_when_no_market_cap(self):
        market = _make_snapshot(price=None, shares=1_000_000)
        sec = {"total_debt": _cited(500_000), "cash": _cited(200_000)}
        bridge = build_ev_bridge(market, sec)

        assert bridge.enterprise_value is not None
        assert bridge.enterprise_value.value is None
        assert any("Market cap" in w for w in bridge.enterprise_value.warnings)
