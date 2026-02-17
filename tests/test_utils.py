"""Tests for shared utility functions: cross-check, compute_gross_profit, compute_free_cash_flow."""

from types import SimpleNamespace

from handspread.analysis._utils import (
    _cross_check,
    compute_free_cash_flow,
    compute_gross_profit,
)


def _cited(value, metric="test", unit=None, concept=None):
    return SimpleNamespace(value=value, metric=metric, unit=unit, concept=concept)


class TestCrossCheck:
    def test_within_tolerance(self):
        assert _cross_check(1000, 1005, "metric") is None

    def test_exceeds_tolerance(self):
        result = _cross_check(1000, 1100, "metric")
        assert result is not None
        assert "metric" in result
        assert "differs from reported" in result

    def test_none_computed(self):
        assert _cross_check(None, 1000, "metric") is None

    def test_none_reported(self):
        assert _cross_check(1000, None, "metric") is None

    def test_zero_reported(self):
        assert _cross_check(1000, 0, "metric") is None

    def test_exact_match(self):
        assert _cross_check(1000, 1000, "metric") is None

    def test_custom_tolerance(self):
        # 5% diff, default 1% tolerance would flag it
        assert _cross_check(1000, 1050, "metric", tolerance=0.01) is not None
        # But 10% tolerance should pass
        assert _cross_check(1000, 1050, "metric", tolerance=0.10) is None


class TestComputeGrossProfit:
    def test_components_present(self):
        sec = {
            "revenue": _cited(1_000_000),
            "cost_of_revenue": _cited(400_000),
        }
        val, cv, warnings = compute_gross_profit(sec)
        assert val == 600_000
        assert cv.value == 600_000
        assert cv.metric == "gross_profit"
        assert cv.formula == "revenue - cost_of_revenue"
        assert "revenue" in cv.components
        assert "cost_of_revenue" in cv.components

    def test_cross_check_warning_when_divergent(self):
        sec = {
            "revenue": _cited(1_000_000),
            "cost_of_revenue": _cited(400_000),
            "gross_profit": _cited(500_000),  # reported differs from 600k computed
        }
        val, cv, warnings = compute_gross_profit(sec)
        assert val == 600_000
        assert any("differs from reported" in w for w in warnings)

    def test_cross_check_warning_includes_concepts(self):
        sec = {
            "revenue": _cited(1_000_000, concept="Revenues"),
            "cost_of_revenue": _cited(400_000, concept="CostOfGoodsAndServicesSold"),
            "gross_profit": _cited(500_000, concept="GrossProfit"),
        }
        val, cv, warnings = compute_gross_profit(sec)
        assert val == 600_000
        divergent = [w for w in warnings if "differs from reported" in w]
        assert len(divergent) == 1
        assert "CostOfGoodsAndServicesSold" in divergent[0]
        assert "GrossProfit" in divergent[0]

    def test_cross_check_no_warning_when_matching(self):
        sec = {
            "revenue": _cited(1_000_000),
            "cost_of_revenue": _cited(400_000),
            "gross_profit": _cited(600_000),
        }
        val, cv, warnings = compute_gross_profit(sec)
        assert val == 600_000
        assert not any("differs from reported" in w for w in warnings)

    def test_fallback_to_reported(self):
        sec = {
            "revenue": _cited(1_000_000),
            "gross_profit": _cited(600_000),
        }
        val, cv, warnings = compute_gross_profit(sec)
        assert val == 600_000
        assert any("pass-through" in w or "reported" in w.lower() for w in warnings)

    def test_both_missing_returns_none(self):
        sec = {"revenue": _cited(1_000_000)}
        val, cv, warnings = compute_gross_profit(sec)
        assert val is None
        assert cv is None
        assert warnings == []

    def test_empty_metrics_returns_none(self):
        val, cv, warnings = compute_gross_profit({})
        assert val is None
        assert cv is None
        assert warnings == []


class TestComputeFreeCashFlow:
    def test_components_present(self):
        sec = {
            "operating_cash_flow": _cited(5_000_000),
            "capex": _cited(1_500_000),
        }
        val, cv, warnings = compute_free_cash_flow(sec)
        assert val == 3_500_000
        assert cv.value == 3_500_000
        assert cv.metric == "free_cash_flow"
        assert cv.formula == "operating_cash_flow - capex"
        assert "operating_cash_flow" in cv.components
        assert "capex" in cv.components

    def test_cross_check_warning_when_divergent(self):
        sec = {
            "operating_cash_flow": _cited(5_000_000),
            "capex": _cited(1_500_000),
            "free_cash_flow": _cited(2_000_000),  # reported differs from 3.5M computed
        }
        val, cv, warnings = compute_free_cash_flow(sec)
        assert val == 3_500_000
        assert any("differs from reported" in w for w in warnings)

    def test_cross_check_warning_includes_concepts(self):
        sec = {
            "operating_cash_flow": _cited(5_000_000, concept="NetCashFromOperating"),
            "capex": _cited(1_500_000, concept="PaymentsForCapitalExpenditures"),
            "free_cash_flow": _cited(2_000_000, concept="FreeCashFlow"),
        }
        val, cv, warnings = compute_free_cash_flow(sec)
        assert val == 3_500_000
        divergent = [w for w in warnings if "differs from reported" in w]
        assert len(divergent) == 1
        assert "NetCashFromOperating" in divergent[0]
        assert "PaymentsForCapitalExpenditures" in divergent[0]
        assert "FreeCashFlow" in divergent[0]

    def test_cross_check_no_warning_when_matching(self):
        sec = {
            "operating_cash_flow": _cited(5_000_000),
            "capex": _cited(1_500_000),
            "free_cash_flow": _cited(3_500_000),
        }
        val, cv, warnings = compute_free_cash_flow(sec)
        assert val == 3_500_000
        assert not any("differs from reported" in w for w in warnings)

    def test_fallback_to_derived(self):
        sec = {
            "free_cash_flow": _cited(3_500_000),
        }
        val, cv, warnings = compute_free_cash_flow(sec)
        assert val == 3_500_000
        assert any("pass-through" in w or "derived" in w.lower() for w in warnings)

    def test_both_missing_returns_none(self):
        sec = {"operating_cash_flow": _cited(5_000_000)}
        val, cv, warnings = compute_free_cash_flow(sec)
        assert val is None
        assert cv is None
        assert warnings == []

    def test_empty_metrics_returns_none(self):
        val, cv, warnings = compute_free_cash_flow({})
        assert val is None
        assert cv is None
        assert warnings == []
