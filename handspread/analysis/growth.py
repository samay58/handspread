"""YoY growth rates and margin deltas from LTM vs LTM-1 data."""

from __future__ import annotations

from typing import Any

from ..models import ComputedValue
from ._utils import compute_adjusted_ebitda, extract_sec_value

GROWTH_KEYS = ["revenue", "ebitda", "net_income", "eps_diluted", "depreciation_amortization"]


def _has_split_warning(source: Any) -> bool:
    """Check if a source value carries a stock split contamination warning."""
    warnings = getattr(source, "warnings", None)
    if not warnings:
        return False
    return any("stock split contamination" in w.lower() for w in warnings)


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

    # Skip growth when stock split contamination is detected
    if _has_split_warning(ltm_src) or _has_split_warning(ltm1_src):
        components: dict[str, Any] = {}
        if ltm_src is not None:
            components["current"] = ltm_src
        if ltm1_src is not None:
            components["prior"] = ltm1_src
        return ComputedValue(
            metric=f"{metric_name}_yoy",
            value=None,
            unit="pure",
            formula=f"({metric_name}_ltm - {metric_name}_ltm1) / abs({metric_name}_ltm1)",
            components=components,
            warnings=["Skipped: stock split contamination detected in source data"],
        )

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


def _compute_margin(
    metrics: dict[str, Any],
    numerator_key: str,
) -> tuple[float | None, dict[str, Any]]:
    """Extract a margin ratio (numerator / revenue) from a single period's metrics.

    Returns (margin_value, components_dict). Returns (None, {}) if data missing.
    """
    num_val, num_src = extract_sec_value(metrics, numerator_key)
    rev_val, rev_src = extract_sec_value(metrics, "revenue")
    if num_val is None or rev_val is None or rev_val == 0:
        return None, {}
    components: dict[str, Any] = {}
    if num_src is not None:
        components[numerator_key] = num_src
    if rev_src is not None:
        components["revenue"] = rev_src
    return num_val / rev_val, components


def _margin_delta(
    metric_name: str,
    ltm_margin: float | None,
    ltm1_margin: float | None,
    ltm_components: dict[str, Any],
    ltm1_components: dict[str, Any],
) -> ComputedValue | None:
    """Compute margin change as raw decimal delta (0.02 = +200bps)."""
    if ltm_margin is None or ltm1_margin is None:
        return None
    components: dict[str, Any] = {}
    if ltm_components:
        components["current"] = ltm_components
    if ltm1_components:
        components["prior"] = ltm1_components
    return ComputedValue(
        metric=f"{metric_name}_chg",
        value=ltm_margin - ltm1_margin,
        unit="pure",
        formula=f"{metric_name}_ltm - {metric_name}_ltm1",
        components=components,
    )


def compute_growth(
    ltm_metrics: dict[str, Any],
    ltm1_metrics: dict[str, Any],
) -> dict[str, ComputedValue]:
    """Compute YoY growth and margin deltas from LTM vs LTM-1 query results.

    Margin deltas are raw decimal change (0.02 = +200bps expansion).

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

    # Margin deltas: gross and EBITDA
    for num_key, margin_name in [
        ("gross_profit", "gross_margin"),
        ("ebitda", "ebitda_margin"),
    ]:
        ltm_m, ltm_c = _compute_margin(ltm_metrics, num_key)
        ltm1_m, ltm1_c = _compute_margin(ltm1_metrics, num_key)
        cv = _margin_delta(margin_name, ltm_m, ltm1_m, ltm_c, ltm1_c)
        if cv is not None:
            result[f"{margin_name}_chg"] = cv

    # Adjusted EBITDA margin delta
    ltm_rev_val, ltm_rev_src = extract_sec_value(ltm_metrics, "revenue")
    ltm1_rev_val, ltm1_rev_src = extract_sec_value(ltm1_metrics, "revenue")

    ltm_adj_val, ltm_adj_cv, _ = compute_adjusted_ebitda(ltm_metrics)
    ltm1_adj_val, ltm1_adj_cv, _ = compute_adjusted_ebitda(ltm1_metrics)

    ltm_adj_margin = None
    ltm_adj_components: dict[str, Any] = {}
    if ltm_adj_val is not None and ltm_rev_val and ltm_rev_val != 0:
        ltm_adj_margin = ltm_adj_val / ltm_rev_val
        ltm_adj_components = {"adjusted_ebitda": ltm_adj_cv, "revenue": ltm_rev_src}

    ltm1_adj_margin = None
    ltm1_adj_components: dict[str, Any] = {}
    if ltm1_adj_val is not None and ltm1_rev_val and ltm1_rev_val != 0:
        ltm1_adj_margin = ltm1_adj_val / ltm1_rev_val
        ltm1_adj_components = {"adjusted_ebitda": ltm1_adj_cv, "revenue": ltm1_rev_src}

    cv = _margin_delta(
        "adjusted_ebitda_margin",
        ltm_adj_margin,
        ltm1_adj_margin,
        ltm_adj_components,
        ltm1_adj_components,
    )
    if cv is not None:
        result["adjusted_ebitda_margin_chg"] = cv

    return result
