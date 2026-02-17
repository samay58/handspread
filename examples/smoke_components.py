"""Smoke test: verify component-based gross profit and FCF on live tickers."""

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from handspread import analyze_comps


def _dollar(val):
    if val is None:
        return "n/a"
    if abs(val) >= 1e12:
        return f"${val / 1e12:,.1f}T"
    if abs(val) >= 1e9:
        return f"${val / 1e9:,.1f}B"
    if abs(val) >= 1e6:
        return f"${val / 1e6:,.1f}M"
    return f"${val:,.0f}"


def _pct(val):
    if val is None:
        return "n/a"
    return f"{val:+.1%}"


def _mult(val):
    if val is None:
        return "n/a"
    return f"{val:.1f}x"


async def main() -> None:
    # Mix of sectors: big tech, bank (often missing GrossProfit tag), industrial, SaaS
    tickers = ["MSFT", "JPM", "CAT", "CRM"]
    results = await analyze_comps(tickers, period="ltm", tax_rate=0.21)

    for r in results:
        print(f"\n{'=' * 70}")
        print(f"  {r.company_name} ({r.symbol})")
        print(f"{'=' * 70}")

        if r.errors:
            for e in r.errors:
                print(f"  ERROR: {e}")

        # Market data
        if r.market:
            print(f"  Price: ${r.market.price.value:,.2f}   "
                  f"Market Cap: {_dollar(r.market.market_cap.value)}")

        if r.ev_bridge and r.ev_bridge.enterprise_value:
            print(f"  EV: {_dollar(r.ev_bridge.enterprise_value.value)}")

        # Gross margin provenance
        gm = r.operating.get("gross_margin")
        if gm:
            gp_source = gm.components.get("gross_profit")
            source_label = "n/a"
            if gp_source:
                source_label = gp_source.formula
            print(f"\n  Gross Margin: {_pct(gm.value)}")
            print(f"    source: {source_label}")
            if gm.warnings:
                for w in gm.warnings:
                    print(f"    warning: {w}")
        else:
            print(f"\n  Gross Margin: n/a")

        # FCF margin provenance
        fcf_m = r.operating.get("fcf_margin")
        if fcf_m:
            fcf_source = fcf_m.components.get("free_cash_flow")
            source_label = "n/a"
            if fcf_source:
                source_label = fcf_source.formula
            print(f"  FCF Margin: {_pct(fcf_m.value)}")
            print(f"    source: {source_label}")
            if fcf_m.warnings:
                for w in fcf_m.warnings:
                    print(f"    warning: {w}")
        else:
            print(f"  FCF Margin: n/a")

        # Multiples that use computed FCF
        ev_fcf = r.multiples.get("ev_fcf")
        fcf_yield = r.multiples.get("fcf_yield")
        if ev_fcf:
            den = ev_fcf.components.get("denominator")
            den_label = den.formula if den and hasattr(den, "formula") else "n/a"
            print(f"  EV/FCF: {_mult(ev_fcf.value)}  (denom: {den_label})")
        if fcf_yield:
            print(f"  FCF Yield: {_pct(fcf_yield.value)}")

        # Growth margin deltas
        gm_chg = r.growth.get("gross_margin_chg")
        if gm_chg:
            current = gm_chg.components.get("current", {})
            gp_cv = current.get("gross_profit") if isinstance(current, dict) else None
            chg_source = gp_cv.formula if gp_cv and hasattr(gp_cv, "formula") else "n/a"
            print(f"  Gross Margin YoY: {_pct(gm_chg.value)} bps  (via {chg_source})")

        # Key multiples
        ev_rev = r.multiples.get("ev_revenue")
        ev_ebitda = r.multiples.get("ev_ebitda")
        pe = r.multiples.get("pe")
        print(f"\n  EV/Rev: {_mult(ev_rev.value if ev_rev else None)}   "
              f"EV/EBITDA(adj): {_mult(ev_ebitda.value if ev_ebitda else None)}   "
              f"P/E: {_mult(pe.value if pe else None)}")

        rev_yoy = r.growth.get("revenue_yoy")
        print(f"  Rev Growth: {_pct(rev_yoy.value if rev_yoy else None)}")

    print()


if __name__ == "__main__":
    asyncio.run(main())
