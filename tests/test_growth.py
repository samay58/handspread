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

        assert "revenue_yoy" in result
        assert "net_income_yoy" in result
        assert "ebitda_yoy" in result
        assert "eps_diluted_yoy" in result
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


class TestSplitWarningSkipsGrowth:
    """Growth computation should skip metrics when stock split contamination is detected."""

    def test_split_warning_skips_growth(self):
        """LTM-1 value with split warning produces value=None growth."""
        ltm_src = SimpleNamespace(value=2.5, warnings=[])
        ltm1_src = SimpleNamespace(
            value=25.0,
            warnings=[
                "Possible stock split contamination: LTM-derived value differs from annual by 0.1x"
            ],
        )
        ltm = {"eps_diluted": ltm_src}
        ltm1 = {"eps_diluted": ltm1_src}
        result = compute_growth(ltm, ltm1)

        assert "eps_diluted_yoy" in result
        assert result["eps_diluted_yoy"].value is None
        warns = result["eps_diluted_yoy"].warnings
        assert any("stock split contamination" in w.lower() for w in warns)

    def test_normal_growth_no_warning(self):
        """Values without warnings compute growth normally."""
        ltm_src = SimpleNamespace(value=2.5, warnings=[])
        ltm1_src = SimpleNamespace(value=2.0, warnings=[])
        ltm = {"eps_diluted": ltm_src}
        ltm1 = {"eps_diluted": ltm1_src}
        result = compute_growth(ltm, ltm1)

        assert "eps_diluted_yoy" in result
        assert abs(result["eps_diluted_yoy"].value - 0.25) < 0.001


class TestMarginDeltas:
    def test_gross_margin_expansion(self):
        """Gross margin improves from 50% to 60% = +0.10 (1000bps)."""
        ltm = {"revenue": _cited(100), "gross_profit": _cited(60)}
        ltm1 = {"revenue": _cited(100), "gross_profit": _cited(50)}
        result = compute_growth(ltm, ltm1)

        assert "gross_margin_chg" in result
        assert abs(result["gross_margin_chg"].value - 0.10) < 0.001
        assert result["gross_margin_chg"].unit == "pure"

    def test_ebitda_margin_compression(self):
        """EBITDA margin drops from 30% to 25% = -0.05 (-500bps)."""
        ltm = {"revenue": _cited(200), "ebitda": _cited(50)}
        ltm1 = {"revenue": _cited(200), "ebitda": _cited(60)}
        result = compute_growth(ltm, ltm1)

        assert "ebitda_margin_chg" in result
        assert abs(result["ebitda_margin_chg"].value - (-0.05)) < 0.001

    def test_adjusted_ebitda_margin_delta(self):
        """Adj EBITDA margin: LTM = (100+20+10)/200 = 65%, LTM-1 = (80+15+5)/200 = 50%."""
        ltm = {
            "revenue": _cited(200),
            "operating_income": _cited(100),
            "depreciation_amortization": _cited(20),
            "stock_based_compensation": _cited(10),
        }
        ltm1 = {
            "revenue": _cited(200),
            "operating_income": _cited(80),
            "depreciation_amortization": _cited(15),
            "stock_based_compensation": _cited(5),
        }
        result = compute_growth(ltm, ltm1)

        assert "adjusted_ebitda_margin_chg" in result
        # 130/200 - 100/200 = 0.65 - 0.50 = 0.15
        assert abs(result["adjusted_ebitda_margin_chg"].value - 0.15) < 0.001

    def test_margin_unchanged_proportional_scaling(self):
        """Revenue and numerator both double: margin stays flat, delta = 0."""
        ltm = {"revenue": _cited(200), "gross_profit": _cited(100)}
        ltm1 = {"revenue": _cited(100), "gross_profit": _cited(50)}
        result = compute_growth(ltm, ltm1)

        assert "gross_margin_chg" in result
        assert abs(result["gross_margin_chg"].value) < 0.001

    def test_missing_ltm_revenue_skips_margin_delta(self):
        ltm = {"gross_profit": _cited(60)}
        ltm1 = {"revenue": _cited(100), "gross_profit": _cited(50)}
        result = compute_growth(ltm, ltm1)
        assert "gross_margin_chg" not in result

    def test_missing_ltm1_numerator_skips_margin_delta(self):
        ltm = {"revenue": _cited(100), "ebitda": _cited(30)}
        ltm1 = {"revenue": _cited(100)}
        result = compute_growth(ltm, ltm1)
        assert "ebitda_margin_chg" not in result

    def test_margin_delta_component_provenance(self):
        ltm = {"revenue": _cited(200), "gross_profit": _cited(120)}
        ltm1 = {"revenue": _cited(200), "gross_profit": _cited(100)}
        result = compute_growth(ltm, ltm1)

        cv = result["gross_margin_chg"]
        assert "current" in cv.components
        assert "prior" in cv.components
        assert "gross_profit" in cv.components["current"]
        assert "revenue" in cv.components["current"]
