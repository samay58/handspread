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
    unit: str = "x",
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
            unit=unit,
            formula=formula,
            components=components,
            warnings=["Numerator unavailable"],
        )
    if denominator_val is None:
        return ComputedValue(
            metric=metric,
            value=None,
            unit=unit,
            formula=formula,
            components=components,
            warnings=["Denominator unavailable"],
        )
    if denominator_val == 0:
        warnings.append("Denominator is zero")
        return ComputedValue(
            metric=metric,
            value=None,
            unit=unit,
            formula=formula,
            components=components,
            warnings=warnings,
        )
    if denominator_val < 0:
        warnings.append(f"Negative denominator ({denominator_val}); result may be misleading")

    return ComputedValue(
        metric=metric,
        value=numerator_val / denominator_val,
        unit=unit,
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
    mcap_val = market.market_cap.value
    price_val = market.price.value

    sec_values = {
        key: extract_sec_value(sec_metrics, key)
        for key in (
            "revenue",
            "ebitda",
            "operating_income",
            "free_cash_flow",
            "net_income",
            "stockholders_equity",
            "dividends_per_share",
        )
    }

    ev_defs = [
        ("ev_revenue", "revenue", "enterprise_value / revenue"),
        ("ev_ebitda", "ebitda", "enterprise_value / ebitda"),
        ("ev_ebit", "operating_income", "enterprise_value / operating_income"),
        ("ev_fcf", "free_cash_flow", "enterprise_value / free_cash_flow"),
    ]
    for metric_name, den_key, formula in ev_defs:
        den_val, den_src = sec_values[den_key]
        result[metric_name] = _safe_divide(
            ev_val,
            den_val,
            metric_name,
            formula,
            ev_bridge.enterprise_value,
            den_src,
        )

    equity_defs = [
        ("pe", "net_income", "market_cap / net_income"),
        ("price_book", "stockholders_equity", "market_cap / stockholders_equity"),
    ]
    for metric_name, den_key, formula in equity_defs:
        den_val, den_src = sec_values[den_key]
        result[metric_name] = _safe_divide(
            mcap_val,
            den_val,
            metric_name,
            formula,
            market.market_cap,
            den_src,
        )

    fcf_val, fcf_src = sec_values["free_cash_flow"]
    result["fcf_yield"] = _safe_divide(
        fcf_val,
        mcap_val,
        "fcf_yield",
        "free_cash_flow / market_cap",
        fcf_src,
        market.market_cap,
        unit="pure",
    )

    dps_val, dps_src = sec_values["dividends_per_share"]
    result["dividend_yield"] = _safe_divide(
        dps_val,
        price_val,
        "dividend_yield",
        "dividends_per_share / price",
        dps_src,
        market.price,
        unit="pure",
    )

    return result
