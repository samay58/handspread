"""Enterprise value bridge construction."""

from __future__ import annotations

from typing import Any

from ..models import ComputedValue, EVBridge, EVPolicy, MarketSnapshot
from ._utils import extract_sec_value


def _apply_component(
    ev: float,
    value: float | None,
    source: Any,
    key: str,
    formula_label: str,
    sign: int,
    components: dict[str, Any],
    formula_parts: list[str],
    bridge: EVBridge,
    bridge_attr: str,
) -> float:
    if value is None:
        return ev
    ev += sign * value
    operator = "+" if sign > 0 else "-"
    formula_parts.append(f"{operator} {formula_label}")
    components[key] = source
    setattr(bridge, bridge_attr, source)
    return ev


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

    # Check for currency mismatch between SEC data and market data (USD)
    sec_currency = None
    for cv_or_list in sec_metrics.values():
        cv = cv_or_list[0] if isinstance(cv_or_list, list) else cv_or_list
        if cv is not None and hasattr(cv, "unit") and cv.unit:
            sec_currency = cv.unit
            break

    if sec_currency is not None and sec_currency != "USD":
        bridge.enterprise_value = ComputedValue(
            metric="enterprise_value",
            value=None,
            unit="USD",
            formula="equity_value + debt - cash + adjustments",
            warnings=[
                f"SEC data is in {sec_currency} but market data is in USD; "
                "cannot mix currencies in EV bridge"
            ],
        )
        return bridge

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
    debt_val, debt_cv = extract_sec_value(sec_metrics, "total_debt")
    short_debt_val, short_debt_cv = extract_sec_value(sec_metrics, "short_term_debt")

    if policy.debt_mode == "total_only":
        if debt_val is not None:
            ev = _apply_component(
                ev=ev,
                value=debt_val,
                source=debt_cv,
                key="total_debt",
                formula_label="total_debt",
                sign=1,
                components=components,
                formula_parts=formula_parts,
                bridge=bridge,
                bridge_attr="total_debt",
            )
        else:
            warnings.append("total_debt missing, treated as 0")
    elif policy.debt_mode == "split":
        if debt_val is not None:
            ev = _apply_component(
                ev=ev,
                value=debt_val,
                source=debt_cv,
                key="total_debt",
                formula_label="total_debt(long)",
                sign=1,
                components=components,
                formula_parts=formula_parts,
                bridge=bridge,
                bridge_attr="total_debt",
            )
        if short_debt_val is not None:
            ev = _apply_component(
                ev=ev,
                value=short_debt_val,
                source=short_debt_cv,
                key="short_term_debt",
                formula_label="short_term_debt",
                sign=1,
                components=components,
                formula_parts=formula_parts,
                bridge=bridge,
                bridge_attr="short_term_debt",
            )
        if debt_val is not None and short_debt_val is not None:
            warnings.append(
                "Using split debt mode: verify no overlap between total_debt and short_term_debt"
            )
    elif policy.debt_mode == "total_plus_short":
        if debt_val is not None:
            ev = _apply_component(
                ev=ev,
                value=debt_val,
                source=debt_cv,
                key="total_debt",
                formula_label="total_debt",
                sign=1,
                components=components,
                formula_parts=formula_parts,
                bridge=bridge,
                bridge_attr="total_debt",
            )
        if short_debt_val is not None:
            ev = _apply_component(
                ev=ev,
                value=short_debt_val,
                source=short_debt_cv,
                key="short_term_debt",
                formula_label="short_term_debt",
                sign=1,
                components=components,
                formula_parts=formula_parts,
                bridge=bridge,
                bridge_attr="short_term_debt",
            )

    # Extract cash and marketable securities (used in both EV calc and net debt)
    cash_val, cash_cv = extract_sec_value(sec_metrics, "cash")
    ms_val, ms_cv = extract_sec_value(sec_metrics, "marketable_securities")

    # Cash subtraction
    if policy.cash_treatment == "subtract":
        if cash_val is not None:
            ev = _apply_component(
                ev=ev,
                value=cash_val,
                source=cash_cv,
                key="cash",
                formula_label="cash",
                sign=-1,
                components=components,
                formula_parts=formula_parts,
                bridge=bridge,
                bridge_attr="cash_and_equivalents",
            )
        else:
            warnings.append("cash missing, treated as 0")

        if ms_val is not None:
            ev = _apply_component(
                ev=ev,
                value=ms_val,
                source=ms_cv,
                key="marketable_securities",
                formula_label="marketable_securities",
                sign=-1,
                components=components,
                formula_parts=formula_parts,
                bridge=bridge,
                bridge_attr="marketable_securities",
            )

    # Operating lease liabilities
    if policy.include_leases:
        lease_val, lease_cv = extract_sec_value(sec_metrics, "operating_lease_liabilities")
        if lease_val is not None:
            ev = _apply_component(
                ev=ev,
                value=lease_val,
                source=lease_cv,
                key="operating_lease_liabilities",
                formula_label="operating_lease_liabilities",
                sign=1,
                components=components,
                formula_parts=formula_parts,
                bridge=bridge,
                bridge_attr="operating_lease_liabilities",
            )
        else:
            warnings.append("operating_lease_liabilities requested but missing")

    # Preferred stock
    pref_val, pref_cv = extract_sec_value(sec_metrics, "preferred_stock")
    if pref_val is not None:
        ev = _apply_component(
            ev=ev,
            value=pref_val,
            source=pref_cv,
            key="preferred_stock",
            formula_label="preferred_stock",
            sign=1,
            components=components,
            formula_parts=formula_parts,
            bridge=bridge,
            bridge_attr="preferred_stock",
        )

    # Noncontrolling interests
    nci_val, nci_cv = extract_sec_value(sec_metrics, "noncontrolling_interests")
    if nci_val is not None:
        ev = _apply_component(
            ev=ev,
            value=nci_val,
            source=nci_cv,
            key="noncontrolling_interests",
            formula_label="noncontrolling_interests",
            sign=1,
            components=components,
            formula_parts=formula_parts,
            bridge=bridge,
            bridge_attr="noncontrolling_interests",
        )

    # Equity method investments
    if policy.subtract_equity_method_investments:
        emi_val, emi_cv = extract_sec_value(sec_metrics, "equity_method_investments")
        if emi_val is not None:
            ev = _apply_component(
                ev=ev,
                value=emi_val,
                source=emi_cv,
                key="equity_method_investments",
                formula_label="equity_method_investments",
                sign=-1,
                components=components,
                formula_parts=formula_parts,
                bridge=bridge,
                bridge_attr="equity_method_investments",
            )

    # Net debt (reuses cash_val and ms_val extracted above)
    debt_total = 0.0
    cash_total = 0.0
    if debt_val is not None:
        debt_total += debt_val
    if short_debt_val is not None and policy.debt_mode != "total_only":
        debt_total += short_debt_val
    if cash_val is not None:
        cash_total += cash_val
    if ms_val is not None:
        cash_total += ms_val

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
