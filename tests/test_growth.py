"""Tests for year-over-year growth computation."""

from types import SimpleNamespace

from handspread.analysis.growth import compute_growth


def _cited(value):
    """Stub CitedValue with .value attribute for growth series tests."""
    return SimpleNamespace(value=value)


class TestYoYGrowth:
    def test_basic_revenue_growth(self):
        metrics = {"revenue": [_cited(120), _cited(100)]}
        result = compute_growth(metrics)

        assert "revenue_yoy" in result
        assert abs(result["revenue_yoy"].value - 0.2) < 0.001

    def test_negative_growth(self):
        metrics = {"revenue": [_cited(80), _cited(100)]}
        result = compute_growth(metrics)

        assert abs(result["revenue_yoy"].value - (-0.2)) < 0.001

    def test_multiple_metrics(self):
        metrics = {
            "revenue": [_cited(110), _cited(100)],
            "net_income": [_cited(22), _cited(20)],
            "ebitda": [_cited(55), _cited(50)],
            "eps_diluted": [_cited(2.2), _cited(2.0)],
        }
        result = compute_growth(metrics)

        assert len(result) == 4
        assert abs(result["revenue_yoy"].value - 0.1) < 0.001
        assert abs(result["eps_diluted_yoy"].value - 0.1) < 0.001


class TestMissingPrior:
    def test_single_value_skipped(self):
        metrics = {"revenue": [_cited(100)]}
        result = compute_growth(metrics)
        assert "revenue_yoy" not in result

    def test_none_metric_skipped(self):
        metrics = {"revenue": None}
        result = compute_growth(metrics)
        assert "revenue_yoy" not in result


class TestNegativePrior:
    def test_negative_prior_uses_abs(self):
        metrics = {"net_income": [_cited(10), _cited(-20)]}
        result = compute_growth(metrics)

        # (10 - (-20)) / abs(-20) = 30/20 = 1.5
        assert abs(result["net_income_yoy"].value - 1.5) < 0.001
        assert any("negative" in w for w in result["net_income_yoy"].warnings)

    def test_zero_prior_returns_none(self):
        metrics = {"revenue": [_cited(100), _cited(0)]}
        result = compute_growth(metrics)

        assert result["revenue_yoy"].value is None
        assert any("zero" in w for w in result["revenue_yoy"].warnings)


class TestNegativeToNegativeTransition:
    def test_negative_to_negative(self):
        """Both years negative: (-10 - (-20)) / abs(-20) = 10/20 = 0.5."""
        metrics = {"net_income": [_cited(-10), _cited(-20)]}
        result = compute_growth(metrics)

        assert abs(result["net_income_yoy"].value - 0.5) < 0.001
        assert any("negative" in w for w in result["net_income_yoy"].warnings)


class TestThreeYearSeriesUsesFirstTwo:
    def test_three_year_series(self):
        """Series length 3: only [0] and [1] used for YoY growth."""
        metrics = {"revenue": [_cited(300), _cited(200), _cited(100)]}
        result = compute_growth(metrics)

        # Growth = (300 - 200) / 200 = 0.5
        assert abs(result["revenue_yoy"].value - 0.5) < 0.001
