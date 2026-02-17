"""Operating efficiency ratios and per-share metrics."""

from __future__ import annotations

from typing import Any

from ..models import ComputedValue, MarketSnapshot
from ._utils import cross_currency_warning, extract_sec_value, infer_currency_from_source


def _pct_of_revenue(
    sec_metrics: dict[str, Any],
    numerator_key: str,
    metric_name: str,
    rev_val: float | None,
    rev_src: Any,
) -> ComputedValue | None:
    """Compute a metric as a percentage of revenue."""
    num_val, num_src = extract_sec_value(sec_metrics, numerator_key)
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
    tax_rate: float = 0.21,
) -> dict[str, ComputedValue]:
    """Compute operating efficiency metrics."""
    result: dict[str, ComputedValue] = {}
    rev_val, rev_src = extract_sec_value(sec_metrics, "revenue")
    rev_currency = infer_currency_from_source(rev_src)

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
            revenue_per_share_currency = rev_currency or "USD"
            warnings: list[str] = []
            if rev_currency is not None and rev_currency != "USD":
                warnings.append(cross_currency_warning(rev_currency, "revenue_per_share"))
            result["revenue_per_share"] = ComputedValue(
                metric="revenue_per_share",
                value=rev_val / shares_val,
                unit=f"{revenue_per_share_currency}/shares",
                formula="revenue / shares_outstanding",
                components={"revenue": rev_src, "shares_outstanding": market.shares_outstanding},
                warnings=warnings,
            )

    # ROIC approximation: operating_income * (1 - tax_rate) / (total_debt + stockholders_equity)
    oi_val, oi_src = extract_sec_value(sec_metrics, "operating_income")
    debt_val, debt_src = extract_sec_value(sec_metrics, "total_debt")
    eq_val, eq_src = extract_sec_value(sec_metrics, "stockholders_equity")

    if oi_val is not None and debt_val is not None and eq_val is not None:
        invested_capital = debt_val + eq_val
        if invested_capital > 0:
            nopat = oi_val * (1 - tax_rate)
            result["roic"] = ComputedValue(
                metric="roic",
                value=nopat / invested_capital,
                unit="pure",
                formula=(
                    f"operating_income * (1 - {tax_rate:g}) / (total_debt + stockholders_equity)"
                ),
                components={
                    "operating_income": oi_src,
                    "total_debt": debt_src,
                    "stockholders_equity": eq_src,
                },
                warnings=[f"ROIC uses assumed {tax_rate:.1%} tax rate; actual rate may differ"],
            )

    return result
