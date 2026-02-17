"""Tests for year-over-year growth computation (LTM vs LTM-1)."""

from types import SimpleNamespace

from handspread.analysis.growth import compute_growth


def _cited(value):
    """Stub CitedValue with .value attribute for growth tests."""
    return SimpleNamespace(value=value)


class TestBasicGrowth:
    def test_revenue_growth(self):
        ltm = {"revenue": _cited(120)}
        ltm1 = {"revenue": _cited(100)}
        result = compute_growth(ltm, ltm1)

        assert "revenue_yoy" in result
        assert abs(result["revenue_yoy"].value - 0.2) < 0.001

    def test_negative_growth(self):
        ltm = {"revenue": _cited(80)}
        ltm1 = {"revenue": _cited(100)}
        result = compute_growth(ltm, ltm1)

        assert abs(result["revenue_yoy"].value - (-0.2)) < 0.001

    def test_multiple_metrics(self):
        ltm = {
            "revenue": _cited(110),
            "net_income": _cited(22),
            "ebitda": _cited(55),
            "eps_diluted": _cited(2.2),
        }
        ltm1 = {
            "revenue": _cited(100),
            "net_income": _cited(20),
            "ebitda": _cited(50),
            "eps_diluted": _cited(2.0),
        }
        result = compute_growth(ltm, ltm1)

        assert len(result) == 4
        assert abs(result["revenue_yoy"].value - 0.1) < 0.001
        assert abs(result["eps_diluted_yoy"].value - 0.1) < 0.001

    def test_zero_growth(self):
        ltm = {"revenue": _cited(100)}
        ltm1 = {"revenue": _cited(100)}
        result = compute_growth(ltm, ltm1)

        assert result["revenue_yoy"].value == 0.0


class TestMissingMetrics:
    def test_missing_from_ltm_skipped(self):
        ltm = {}
        ltm1 = {"revenue": _cited(100)}
        result = compute_growth(ltm, ltm1)
        assert "revenue_yoy" not in result

    def test_missing_from_ltm1_skipped(self):
        ltm = {"revenue": _cited(120)}
        ltm1 = {}
        result = compute_growth(ltm, ltm1)
        assert "revenue_yoy" not in result

    def test_both_empty(self):
        result = compute_growth({}, {})
        assert result == {}

    def test_none_value_in_ltm_skipped(self):
        ltm = {"revenue": _cited(None)}
        ltm1 = {"revenue": _cited(100)}
        result = compute_growth(ltm, ltm1)
        assert "revenue_yoy" not in result

    def test_none_value_in_ltm1_skipped(self):
        ltm = {"revenue": _cited(120)}
        ltm1 = {"revenue": _cited(None)}
        result = compute_growth(ltm, ltm1)
        assert "revenue_yoy" not in result


class TestEdgeCases:
    def test_negative_prior_uses_abs(self):
        ltm = {"net_income": _cited(10)}
        ltm1 = {"net_income": _cited(-20)}
        result = compute_growth(ltm, ltm1)

        # (10 - (-20)) / abs(-20) = 30/20 = 1.5
        assert abs(result["net_income_yoy"].value - 1.5) < 0.001
        assert any("negative" in w for w in result["net_income_yoy"].warnings)

    def test_zero_prior_returns_none(self):
        ltm = {"revenue": _cited(100)}
        ltm1 = {"revenue": _cited(0)}
        result = compute_growth(ltm, ltm1)

        assert result["revenue_yoy"].value is None
        assert any("zero" in w for w in result["revenue_yoy"].warnings)

    def test_negative_to_negative(self):
        """Both years negative: (-10 - (-20)) / abs(-20) = 10/20 = 0.5."""
        ltm = {"net_income": _cited(-10)}
        ltm1 = {"net_income": _cited(-20)}
        result = compute_growth(ltm, ltm1)

        assert abs(result["net_income_yoy"].value - 0.5) < 0.001
        assert any("negative" in w for w in result["net_income_yoy"].warnings)


class TestComponentProvenance:
    def test_components_carry_sources(self):
        ltm_src = _cited(120)
        ltm1_src = _cited(100)
        ltm = {"revenue": ltm_src}
        ltm1 = {"revenue": ltm1_src}
        result = compute_growth(ltm, ltm1)

        cv = result["revenue_yoy"]
        assert cv.components["current"] is ltm_src
        assert cv.components["prior"] is ltm1_src
