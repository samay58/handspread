"""Year-over-year growth calculations from LTM vs LTM-1 data."""

from __future__ import annotations

from typing import Any

from ..models import ComputedValue
from ._utils import extract_sec_value

GROWTH_KEYS = ["revenue", "ebitda", "net_income", "eps_diluted", "depreciation_amortization"]


def _safe_growth(
    metric_name: str,
    ltm_val: float | None,
    ltm1_val: float | None,
    ltm_src: Any,
    ltm1_src: Any,
) -> ComputedValue | None:
    """Compute YoY growth from LTM and LTM-1 values."""
    if ltm_val is None or ltm1_val is None:
        return None

    formula = f"({metric_name}_ltm - {metric_name}_ltm1) / abs({metric_name}_ltm1)"
    warnings: list[str] = []
    components: dict[str, Any] = {}
    if ltm_src is not None:
        components["current"] = ltm_src
    if ltm1_src is not None:
        components["prior"] = ltm1_src

    if ltm1_val == 0:
        return ComputedValue(
            metric=f"{metric_name}_yoy",
            value=None,
            unit="pure",
            formula=formula,
            components=components,
            warnings=["Prior period value is zero; cannot compute growth"],
        )

    if ltm1_val < 0:
        warnings.append(f"Prior period value is negative ({ltm1_val}); using abs() for denominator")

    growth = (ltm_val - ltm1_val) / abs(ltm1_val)

    return ComputedValue(
        metric=f"{metric_name}_yoy",
        value=growth,
        unit="pure",
        formula=formula,
        components=components,
        warnings=warnings,
    )


def compute_growth(
    ltm_metrics: dict[str, Any],
    ltm1_metrics: dict[str, Any],
) -> dict[str, ComputedValue]:
    """Compute YoY growth for key metrics from LTM vs LTM-1 query results.

    ltm_metrics: single CitedValue per key from the LTM period query.
    ltm1_metrics: single CitedValue per key from the LTM-1 period query.
    """
    result: dict[str, ComputedValue] = {}

    for key in GROWTH_KEYS:
        ltm_val, ltm_src = extract_sec_value(ltm_metrics, key)
        ltm1_val, ltm1_src = extract_sec_value(ltm1_metrics, key)
        cv = _safe_growth(key, ltm_val, ltm1_val, ltm_src, ltm1_src)
        if cv is not None:
            result[f"{key}_yoy"] = cv

    return result
