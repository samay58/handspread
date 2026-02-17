"""Shared utilities for analysis modules."""

from __future__ import annotations

from typing import Any


def extract_sec_value(sec_metrics: dict[str, Any], key: str) -> tuple[float | None, Any]:
    """Extract a numeric value and its source object from sec_metrics.

    Handles both single CitedValue and list[CitedValue] (from series queries).
    Returns (value, source_object) or (None, None) if missing.
    """
    cv = sec_metrics.get(key)
    if cv is None:
        return None, None
    if isinstance(cv, list):
        cv = cv[0] if cv else None
    if cv is None:
        return None, None
    return getattr(cv, "value", None), cv


def infer_currency_from_unit(unit: str | None) -> str | None:
    """Extract currency code from a unit string.

    Examples:
    - "USD" -> "USD"
    - "JPY/shares" -> "JPY"
    - "shares" -> None
    - "pure" -> None
    """
    if not unit:
        return None

    cleaned = unit.strip()
    if not cleaned:
        return None

    lower = cleaned.lower()
    if lower in {"shares", "share", "pure", "ratio", "percent", "%"}:
        return None

    currency_part = cleaned.split("/", 1)[0].strip()
    if not currency_part:
        return None
    if currency_part.lower() in {"shares", "share", "pure", "ratio", "percent", "%"}:
        return None
    return currency_part.upper()


def infer_currency_from_source(source: Any) -> str | None:
    """Extract a currency code from an object that may have a .unit field."""
    if source is None:
        return None
    unit = getattr(source, "unit", None)
    if not isinstance(unit, str):
        return None
    return infer_currency_from_unit(unit)


def detect_sec_currency(
    sec_metrics: dict[str, Any],
    keys: tuple[str, ...] | None = None,
) -> str | None:
    """Return the first currency code found in SEC metric sources.

    If keys are provided, inspect only those metrics; otherwise inspect all.
    """
    metric_keys = keys if keys is not None else tuple(sec_metrics.keys())

    for key in metric_keys:
        source = sec_metrics.get(key)
        if source is None:
            continue
        if isinstance(source, list):
            for item in source:
                currency = infer_currency_from_source(item)
                if currency is not None:
                    return currency
            continue
        currency = infer_currency_from_source(source)
        if currency is not None:
            return currency

    return None


def cross_currency_warning(sec_currency: str, context: str) -> str:
    """Generate a consistent cross-currency warning message."""
    return (
        f"SEC data is in {sec_currency} but market data is in USD; "
        f"cannot mix currencies in {context}"
    )


def _cross_check(
    computed: float | None,
    reported: float | None,
    metric_name: str,
    tolerance: float = 0.01,
) -> str | None:
    """Compare computed value against reported/vendor value.

    Returns a warning string if relative divergence exceeds tolerance.
    Returns None if they agree or if either value is None.
    """
    if computed is None or reported is None or reported == 0:
        return None
    rel_diff = abs(computed - reported) / abs(reported)
    if rel_diff > tolerance:
        return (
            f"{metric_name}: computed ({computed:,.0f}) differs from reported "
            f"({reported:,.0f}) by {rel_diff:.1%}"
        )
    return None


def compute_gross_profit(
    sec_metrics: dict[str, Any],
) -> tuple[float | None, Any | None, list[str]]:
    """Compute gross profit = revenue - cost_of_revenue.

    Returns (gross_profit_value, gross_profit_computed_value, warnings).
    Falls back to reported gross_profit if components are missing.
    """
    from ..models import ComputedValue

    rev_val, rev_src = extract_sec_value(sec_metrics, "revenue")
    cogs_val, cogs_src = extract_sec_value(sec_metrics, "cost_of_revenue")

    warnings: list[str] = []

    if rev_val is not None and cogs_val is not None:
        computed_val = rev_val - cogs_val

        # Cross-check against reported gross_profit if available
        reported_val, reported_src = extract_sec_value(sec_metrics, "gross_profit")
        xcheck = _cross_check(computed_val, reported_val, "gross_profit")
        if xcheck is not None:
            cogs_concept = getattr(cogs_src, "concept", None)
            gp_concept = getattr(reported_src, "concept", None)
            tag_detail = f" [computed from {cogs_concept}; reported from {gp_concept}]"
            warnings.append(xcheck + tag_detail)

        components: dict[str, Any] = {}
        if rev_src is not None:
            components["revenue"] = rev_src
        if cogs_src is not None:
            components["cost_of_revenue"] = cogs_src

        cv = ComputedValue(
            metric="gross_profit",
            value=computed_val,
            unit="USD",
            formula="revenue - cost_of_revenue",
            components=components,
            warnings=warnings,
        )
        return computed_val, cv, warnings

    # Fallback: use reported gross_profit if components missing
    gp_val, gp_src = extract_sec_value(sec_metrics, "gross_profit")
    if gp_val is not None:
        warnings.append("Using reported gross_profit (cost_of_revenue unavailable)")
        cv = ComputedValue(
            metric="gross_profit",
            value=gp_val,
            unit="USD",
            formula="reported gross_profit (pass-through)",
            components={"gross_profit": gp_src} if gp_src is not None else {},
            warnings=warnings,
        )
        return gp_val, cv, warnings

    return None, None, []


def compute_free_cash_flow(
    sec_metrics: dict[str, Any],
) -> tuple[float | None, Any | None, list[str]]:
    """Compute free cash flow = operating_cash_flow - capex.

    Returns (fcf_value, fcf_computed_value, warnings).
    Falls back to edgarpack's derived free_cash_flow if components are missing.
    """
    from ..models import ComputedValue

    ocf_val, ocf_src = extract_sec_value(sec_metrics, "operating_cash_flow")
    capex_val, capex_src = extract_sec_value(sec_metrics, "capex")

    warnings: list[str] = []

    if ocf_val is not None and capex_val is not None:
        computed_val = ocf_val - capex_val

        # Cross-check against edgarpack's derived free_cash_flow if available
        reported_val, reported_src = extract_sec_value(sec_metrics, "free_cash_flow")
        xcheck = _cross_check(computed_val, reported_val, "free_cash_flow")
        if xcheck is not None:
            ocf_concept = getattr(ocf_src, "concept", None)
            capex_concept = getattr(capex_src, "concept", None)
            fcf_concept = getattr(reported_src, "concept", None)
            tag_detail = (
                f" [computed from {ocf_concept} - {capex_concept}; reported from {fcf_concept}]"
            )
            warnings.append(xcheck + tag_detail)

        components: dict[str, Any] = {}
        if ocf_src is not None:
            components["operating_cash_flow"] = ocf_src
        if capex_src is not None:
            components["capex"] = capex_src

        cv = ComputedValue(
            metric="free_cash_flow",
            value=computed_val,
            unit="USD",
            formula="operating_cash_flow - capex",
            components=components,
            warnings=warnings,
        )
        return computed_val, cv, warnings

    # Fallback: use edgarpack's derived free_cash_flow
    fcf_val, fcf_src = extract_sec_value(sec_metrics, "free_cash_flow")
    if fcf_val is not None:
        warnings.append("Using derived free_cash_flow (OCF or capex unavailable)")
        cv = ComputedValue(
            metric="free_cash_flow",
            value=fcf_val,
            unit="USD",
            formula="derived free_cash_flow (pass-through)",
            components={"free_cash_flow": fcf_src} if fcf_src is not None else {},
            warnings=warnings,
        )
        return fcf_val, cv, warnings

    return None, None, []


def compute_adjusted_ebitda(
    sec_metrics: dict[str, Any],
) -> tuple[float | None, Any | None, list[str]]:
    """Compute adjusted EBITDA = operating_income + D&A + SBC.

    Returns (adj_ebitda_value, adj_ebitda_computed_value, warnings).
    """
    from ..models import ComputedValue

    oi_val, oi_src = extract_sec_value(sec_metrics, "operating_income")
    da_val, da_src = extract_sec_value(sec_metrics, "depreciation_amortization")
    sbc_val, sbc_src = extract_sec_value(sec_metrics, "stock_based_compensation")

    warnings: list[str] = []

    if oi_val is None or da_val is None:
        return None, None, warnings

    adj_val = oi_val + da_val + (sbc_val or 0)
    if sbc_val is None:
        warnings.append("SBC unavailable; adjusted EBITDA equals GAAP EBITDA")

    components: dict[str, Any] = {}
    if oi_src is not None:
        components["operating_income"] = oi_src
    if da_src is not None:
        components["depreciation_amortization"] = da_src
    if sbc_src is not None:
        components["stock_based_compensation"] = sbc_src

    cv = ComputedValue(
        metric="adjusted_ebitda",
        value=adj_val,
        unit="USD",
        formula="operating_income + depreciation_amortization + stock_based_compensation",
        components=components,
        warnings=warnings,
    )
    return adj_val, cv, warnings
