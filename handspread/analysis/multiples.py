"""Valuation multiples: EV-based and equity-based."""

from __future__ import annotations

from typing import Any

from ..models import ComputedValue, EVBridge, MarketSnapshot
from ._utils import extract_sec_value


def _safe_divide(
    numerator_val: float | None,
    denominator_val: float | None,
    metric: str,
    formula: str,
    num_source: Any = None,
    den_source: Any = None,
) -> ComputedValue:
    """Divide with None/zero protection. Returns ComputedValue with provenance."""
    warnings: list[str] = []
    components: dict[str, Any] = {}

    if num_source is not None:
        components["numerator"] = num_source
    if den_source is not None:
        components["denominator"] = den_source

    if numerator_val is None:
        return ComputedValue(
            metric=metric,
            value=None,
            unit="x",
            formula=formula,
            components=components,
            warnings=["Numerator unavailable"],
        )
    if denominator_val is None:
        return ComputedValue(
            metric=metric,
            value=None,
            unit="x",
            formula=formula,
            components=components,
            warnings=["Denominator unavailable"],
        )
    if denominator_val == 0:
        warnings.append("Denominator is zero")
        return ComputedValue(
            metric=metric,
            value=None,
            unit="x",
            formula=formula,
            components=components,
            warnings=warnings,
        )
    if denominator_val < 0:
        warnings.append(f"Negative denominator ({denominator_val}); multiple may be misleading")

    return ComputedValue(
        metric=metric,
        value=numerator_val / denominator_val,
        unit="x",
        formula=formula,
        components=components,
        warnings=warnings,
    )


def compute_multiples(
    ev_bridge: EVBridge,
    market: MarketSnapshot,
    sec_metrics: dict[str, Any],
) -> dict[str, ComputedValue]:
    """Compute EV-based and equity-based valuation multiples."""
    result: dict[str, ComputedValue] = {}
    ev_val = ev_bridge.enterprise_value.value if ev_bridge.enterprise_value else None

    # EV-based multiples
    rev_val, rev_src = extract_sec_value(sec_metrics, "revenue")
    result["ev_revenue"] = _safe_divide(
        ev_val,
        rev_val,
        "ev_revenue",
        "enterprise_value / revenue",
        ev_bridge.enterprise_value,
        rev_src,
    )

    ebitda_val, ebitda_src = extract_sec_value(sec_metrics, "ebitda")
    result["ev_ebitda"] = _safe_divide(
        ev_val,
        ebitda_val,
        "ev_ebitda",
        "enterprise_value / ebitda",
        ev_bridge.enterprise_value,
        ebitda_src,
    )

    ebit_val, ebit_src = extract_sec_value(sec_metrics, "operating_income")
    result["ev_ebit"] = _safe_divide(
        ev_val,
        ebit_val,
        "ev_ebit",
        "enterprise_value / operating_income",
        ev_bridge.enterprise_value,
        ebit_src,
    )

    fcf_val, fcf_src = extract_sec_value(sec_metrics, "free_cash_flow")
    result["ev_fcf"] = _safe_divide(
        ev_val,
        fcf_val,
        "ev_fcf",
        "enterprise_value / free_cash_flow",
        ev_bridge.enterprise_value,
        fcf_src,
    )

    # Equity-based multiples
    mcap_val = market.market_cap.value
    price_val = market.price.value

    ni_val, ni_src = extract_sec_value(sec_metrics, "net_income")
    result["pe"] = _safe_divide(
        mcap_val,
        ni_val,
        "pe",
        "market_cap / net_income",
        market.market_cap,
        ni_src,
    )

    bv_val, bv_src = extract_sec_value(sec_metrics, "stockholders_equity")
    result["price_book"] = _safe_divide(
        mcap_val,
        bv_val,
        "price_book",
        "market_cap / stockholders_equity",
        market.market_cap,
        bv_src,
    )

    # FCF yield = free_cash_flow / market_cap
    result["fcf_yield"] = _safe_divide(
        fcf_val,
        mcap_val,
        "fcf_yield",
        "free_cash_flow / market_cap",
        fcf_src,
        market.market_cap,
    )

    # Dividend yield = dividends_per_share / price
    dps_val, dps_src = extract_sec_value(sec_metrics, "dividends_per_share")
    result["dividend_yield"] = _safe_divide(
        dps_val,
        price_val,
        "dividend_yield",
        "dividends_per_share / price",
        dps_src,
        market.price,
    )

    return result
