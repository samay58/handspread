"""Operating efficiency ratios and per-share metrics."""

from __future__ import annotations

from typing import Any

from ..models import ComputedValue, MarketSnapshot


def _extract_value(sec_metrics: dict[str, Any], key: str) -> tuple[float | None, Any]:
    cv = sec_metrics.get(key)
    if cv is None:
        return None, None
    if isinstance(cv, list):
        cv = cv[0] if cv else None
    if cv is None:
        return None, None
    return cv.value, cv


def _pct_of_revenue(
    sec_metrics: dict[str, Any],
    numerator_key: str,
    metric_name: str,
    rev_val: float | None,
    rev_src: Any,
) -> ComputedValue | None:
    """Compute a metric as a percentage of revenue."""
    num_val, num_src = _extract_value(sec_metrics, numerator_key)
    if num_val is None or rev_val is None or rev_val == 0:
        return None

    return ComputedValue(
        metric=metric_name,
        value=num_val / rev_val,
        unit="pure",
        formula=f"{numerator_key} / revenue",
        components={"numerator": num_src, "revenue": rev_src},
    )


def compute_operating(
    sec_metrics: dict[str, Any],
    market: MarketSnapshot | None = None,
) -> dict[str, ComputedValue]:
    """Compute operating efficiency metrics."""
    result: dict[str, ComputedValue] = {}
    rev_val, rev_src = _extract_value(sec_metrics, "revenue")

    # R&D as % of revenue
    cv = _pct_of_revenue(sec_metrics, "rd_expense", "rd_pct_revenue", rev_val, rev_src)
    if cv is not None:
        result["rd_pct_revenue"] = cv

    # SG&A as % of revenue
    cv = _pct_of_revenue(sec_metrics, "sga_expense", "sga_pct_revenue", rev_val, rev_src)
    if cv is not None:
        result["sga_pct_revenue"] = cv

    # Capex as % of revenue
    cv = _pct_of_revenue(sec_metrics, "capex", "capex_pct_revenue", rev_val, rev_src)
    if cv is not None:
        result["capex_pct_revenue"] = cv

    # Revenue per share
    if market is not None and rev_val is not None:
        shares_val = market.shares_outstanding.value
        if shares_val is not None and shares_val > 0:
            result["revenue_per_share"] = ComputedValue(
                metric="revenue_per_share",
                value=rev_val / shares_val,
                unit="USD/shares",
                formula="revenue / shares_outstanding",
                components={"revenue": rev_src, "shares_outstanding": market.shares_outstanding},
            )

    # ROIC approximation: operating_income * (1 - tax_rate) / (total_debt + stockholders_equity)
    oi_val, oi_src = _extract_value(sec_metrics, "operating_income")
    debt_val, debt_src = _extract_value(sec_metrics, "total_debt")
    eq_val, eq_src = _extract_value(sec_metrics, "stockholders_equity")

    if oi_val is not None and debt_val is not None and eq_val is not None:
        invested_capital = debt_val + eq_val
        if invested_capital > 0:
            # Approximate tax rate of 21%
            nopat = oi_val * (1 - 0.21)
            result["roic"] = ComputedValue(
                metric="roic",
                value=nopat / invested_capital,
                unit="pure",
                formula="operating_income * (1 - 0.21) / (total_debt + stockholders_equity)",
                components={
                    "operating_income": oi_src,
                    "total_debt": debt_src,
                    "stockholders_equity": eq_src,
                },
                warnings=["ROIC uses assumed 21% tax rate; actual rate may differ"],
            )

    return result
