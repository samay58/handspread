"""Example: run a comparable company analysis on GPU companies."""

import asyncio

from handspread import analyze_comps


async def main():
    tickers = ["NVDA", "AMD", "INTC"]
    results = await analyze_comps(tickers, period="ltm")

    for r in results:
        print(f"\n{'=' * 60}")
        print(f"{r.company_name} ({r.symbol}) | CIK: {r.cik}")
        print(f"{'=' * 60}")

        if r.errors:
            print(f"  Errors: {r.errors}")

        if r.market:
            print(f"  Price:      ${r.market.price.value:,.2f}")
            print(f"  Shares:     {r.market.shares_outstanding.value:,.0f}")
            if r.market.market_cap_value:
                print(f"  Market Cap: ${r.market.market_cap_value:,.0f}")

        if r.ev_bridge and r.ev_bridge.enterprise_value:
            ev = r.ev_bridge.enterprise_value
            if ev.value:
                print(f"  EV:         ${ev.value:,.0f}")
                print(f"  EV Formula: {ev.formula}")

        if r.multiples:
            print("\n  Multiples:")
            for name, cv in r.multiples.items():
                if cv.value is not None:
                    print(f"    {name}: {cv.value:.2f}x  ({cv.formula})")

        if r.growth:
            print("\n  Growth (YoY):")
            for name, cv in r.growth.items():
                if cv.value is not None:
                    print(f"    {name}: {cv.value:.1%}")

        if r.operating:
            print("\n  Operating:")
            for name, cv in r.operating.items():
                if cv.value is not None:
                    if cv.unit == "pure":
                        print(f"    {name}: {cv.value:.1%}")
                    else:
                        print(f"    {name}: ${cv.value:,.2f}")

    # Provenance chain example
    print("\n\nProvenance chain for first company's EV/Revenue:")
    if results and results[0].multiples.get("ev_revenue"):
        ev_rev = results[0].multiples["ev_revenue"]
        print(f"  Formula: {ev_rev.formula}")
        for comp_name, comp in ev_rev.components.items():
            if hasattr(comp, "citation"):
                print(f"  {comp_name}: {comp.citation}")
            elif hasattr(comp, "formula"):
                print(f"  {comp_name}: computed via {comp.formula}")


if __name__ == "__main__":
    asyncio.run(main())
