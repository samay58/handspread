"""Enterprise value bridge construction."""

from __future__ import annotations

from typing import Any

from edgarpack.query.models import CitedValue

from ..models import ComputedValue, EVBridge, EVPolicy, MarketSnapshot


def _get_sec_value(
    sec_metrics: dict[str, Any], key: str
) -> tuple[float | None, CitedValue | None]:
    """Extract a numeric value and its CitedValue from sec_metrics."""
    cv = sec_metrics.get(key)
    if cv is None:
        return None, None
    if isinstance(cv, list):
        cv = cv[0] if cv else None
    if cv is None:
        return None, None
    return cv.value, cv


def build_ev_bridge(
    market: MarketSnapshot,
    sec_metrics: dict[str, Any],
    policy: EVPolicy | None = None,
) -> EVBridge:
    """Construct an enterprise value bridge from market + SEC data.

    EV = Market Cap + Total Debt - Cash & Equivalents [- Marketable Securities]
         [+ Operating Lease Liabilities] [+ Preferred Stock]
         [+ Noncontrolling Interests] [- Equity Method Investments]
    """
    if policy is None:
        policy = EVPolicy()

    bridge = EVBridge()
    warnings: list[str] = []

    # Equity value = market cap
    mcap = market.market_cap.value
    bridge.equity_value = ComputedValue(
        metric="equity_value",
        value=mcap,
        unit="USD",
        formula="market_cap",
        components={"market_cap": market.market_cap},
    )

    if mcap is None:
        bridge.enterprise_value = ComputedValue(
            metric="enterprise_value",
            value=None,
            unit="USD",
            formula="equity_value + debt - cash + adjustments",
            warnings=["Market cap unavailable; cannot compute EV"],
        )
        return bridge

    ev = mcap
    formula_parts = ["equity_value"]
    components: dict[str, Any] = {"equity_value": bridge.equity_value}

    # Debt handling based on policy
    debt_val, debt_cv = _get_sec_value(sec_metrics, "total_debt")
    short_debt_val, short_debt_cv = _get_sec_value(sec_metrics, "short_term_debt")

    if policy.debt_mode == "total_only":
        if debt_val is not None:
            ev += debt_val
            formula_parts.append("+ total_debt")
            components["total_debt"] = debt_cv
            bridge.total_debt = debt_cv
        else:
            warnings.append("total_debt missing, treated as 0")
    elif policy.debt_mode == "split":
        if debt_val is not None:
            ev += debt_val
            formula_parts.append("+ total_debt(long)")
            components["total_debt"] = debt_cv
            bridge.total_debt = debt_cv
        if short_debt_val is not None:
            ev += short_debt_val
            formula_parts.append("+ short_term_debt")
            components["short_term_debt"] = short_debt_cv
            bridge.short_term_debt = short_debt_cv
        if debt_val is not None and short_debt_val is not None:
            warnings.append(
                "Using split debt mode: verify no overlap between total_debt and short_term_debt"
            )
    elif policy.debt_mode == "total_plus_short":
        if debt_val is not None:
            ev += debt_val
            formula_parts.append("+ total_debt")
            components["total_debt"] = debt_cv
            bridge.total_debt = debt_cv
        if short_debt_val is not None:
            ev += short_debt_val
            formula_parts.append("+ short_term_debt")
            components["short_term_debt"] = short_debt_cv
            bridge.short_term_debt = short_debt_cv

    # Cash subtraction
    if policy.cash_treatment == "subtract":
        cash_val, cash_cv = _get_sec_value(sec_metrics, "cash")
        if cash_val is not None:
            ev -= cash_val
            formula_parts.append("- cash")
            components["cash"] = cash_cv
            bridge.cash_and_equivalents = cash_cv
        else:
            warnings.append("cash missing, treated as 0")

        # Marketable securities
        ms_val, ms_cv = _get_sec_value(sec_metrics, "marketable_securities")
        if ms_val is not None:
            ev -= ms_val
            formula_parts.append("- marketable_securities")
            components["marketable_securities"] = ms_cv
            bridge.marketable_securities = ms_cv

    # Operating lease liabilities
    if policy.include_leases:
        lease_val, lease_cv = _get_sec_value(sec_metrics, "operating_lease_liabilities")
        if lease_val is not None:
            ev += lease_val
            formula_parts.append("+ operating_lease_liabilities")
            components["operating_lease_liabilities"] = lease_cv
            bridge.operating_lease_liabilities = lease_cv
        else:
            warnings.append("operating_lease_liabilities requested but missing")

    # Preferred stock
    pref_val, pref_cv = _get_sec_value(sec_metrics, "preferred_stock")
    if pref_val is not None:
        ev += pref_val
        formula_parts.append("+ preferred_stock")
        components["preferred_stock"] = pref_cv
        bridge.preferred_stock = pref_cv

    # Noncontrolling interests
    nci_val, nci_cv = _get_sec_value(sec_metrics, "noncontrolling_interests")
    if nci_val is not None:
        ev += nci_val
        formula_parts.append("+ noncontrolling_interests")
        components["noncontrolling_interests"] = nci_cv
        bridge.noncontrolling_interests = nci_cv

    # Equity method investments
    if policy.subtract_equity_method_investments:
        emi_val, emi_cv = _get_sec_value(sec_metrics, "equity_method_investments")
        if emi_val is not None:
            ev -= emi_val
            formula_parts.append("- equity_method_investments")
            components["equity_method_investments"] = emi_cv
            bridge.equity_method_investments = emi_cv

    # Net debt
    debt_total = 0.0
    cash_total = 0.0
    if debt_val is not None:
        debt_total += debt_val
    if short_debt_val is not None and policy.debt_mode != "total_only":
        debt_total += short_debt_val
    cash_val_for_net, _ = _get_sec_value(sec_metrics, "cash")
    if cash_val_for_net is not None:
        cash_total += cash_val_for_net
    ms_val_for_net, _ = _get_sec_value(sec_metrics, "marketable_securities")
    if ms_val_for_net is not None:
        cash_total += ms_val_for_net

    bridge.net_debt = ComputedValue(
        metric="net_debt",
        value=debt_total - cash_total,
        unit="USD",
        formula="total_debt - cash - marketable_securities",
    )

    bridge.enterprise_value = ComputedValue(
        metric="enterprise_value",
        value=ev,
        unit="USD",
        formula=" ".join(formula_parts),
        components=components,
        warnings=warnings,
    )

    return bridge
