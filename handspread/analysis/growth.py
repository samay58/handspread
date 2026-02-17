"""Year-over-year growth calculations from annual series data."""

from __future__ import annotations

from typing import Any

from ..models import ComputedValue


def _first_two_valid_points(series: list | None) -> tuple[Any, Any] | None:
    """Return first two non-None entries from a yearly series."""
    if series is None:
        return None
    usable = [item for item in series if item is not None]
    if len(usable) < 2:
        return None
    return usable[0], usable[1]


def _yoy_growth(
    metric_name: str,
    series: list | None,
) -> ComputedValue | None:
    """Compute YoY growth from a list of CitedValues ordered by fiscal year desc.

    Expects series = [current_year, prior_year, ...] (most recent first).
    """
    points = _first_two_valid_points(series)
    if points is None:
        return None

    current, prior = points

    curr_val = current.value if hasattr(current, "value") else None
    prior_val = prior.value if hasattr(prior, "value") else None

    if curr_val is None or prior_val is None:
        return None

    warnings: list[str] = []

    if prior_val == 0:
        return ComputedValue(
            metric=f"{metric_name}_yoy",
            value=None,
            unit="pure",
            formula=f"({metric_name}_current - {metric_name}_prior) / abs({metric_name}_prior)",
            components={"current": current, "prior": prior},
            warnings=["Prior period value is zero; cannot compute growth"],
        )

    if prior_val < 0:
        warnings.append(
            f"Prior period value is negative ({prior_val}); using abs() for denominator"
        )

    growth = (curr_val - prior_val) / abs(prior_val)

    return ComputedValue(
        metric=f"{metric_name}_yoy",
        value=growth,
        unit="pure",
        formula=f"({metric_name}_current - {metric_name}_prior) / abs({metric_name}_prior)",
        components={"current": current, "prior": prior},
        warnings=warnings,
    )


def compute_growth(annual_metrics: dict[str, Any]) -> dict[str, ComputedValue]:
    """Compute YoY growth for key metrics from annual:2 query results.

    annual_metrics values should be list[CitedValue] ordered by fiscal year desc.
    """
    result: dict[str, ComputedValue] = {}

    growth_keys = ["revenue", "ebitda", "net_income", "eps_diluted", "depreciation_amortization"]

    for key in growth_keys:
        series = annual_metrics.get(key)
        if series is not None and not isinstance(series, list):
            continue  # skip derived metrics that aren't returned as series
        cv = _yoy_growth(key, series)
        if cv is not None:
            result[f"{key}_yoy"] = cv

    return result
