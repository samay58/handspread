"""Diagnostic: dump raw XBRL tag resolution for a ticker's key metrics.

Usage:
    .venv/bin/python examples/diagnose_tags.py CAT
    .venv/bin/python examples/diagnose_tags.py CAT JPM MSFT
"""

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from edgarpack.query import comps  # noqa: E402

FOCUS_METRICS = [
    "revenue",
    "cost_of_revenue",
    "gross_profit",
    "operating_cash_flow",
    "capex",
    "free_cash_flow",
    "operating_income",
    "depreciation_amortization",
]


async def main() -> None:
    tickers = sys.argv[1:] or ["CAT"]

    results = await comps(
        companies=tickers,
        metrics=FOCUS_METRICS,
        period="ltm",
    )

    for ticker, qr in results.items():
        print(f"\n{'=' * 72}")
        print(f"  {qr.company} ({ticker})  CIK {qr.cik}  period={qr.period}")
        print(f"{'=' * 72}")

        for metric_name in FOCUS_METRICS:
            cv = qr.metrics.get(metric_name)
            if cv is None:
                print(f"  {metric_name:30s}  -- not found --")
                continue

            # comps() can return a single CitedValue or a list
            items = cv if isinstance(cv, list) else [cv]
            for item in items:
                val = getattr(item, "value", None)
                concept = getattr(item, "concept", "?")
                fy = getattr(item, "fiscal_year", "?")
                fp = getattr(item, "fiscal_period", "?")
                form = getattr(item, "form_type", "?")
                unit = getattr(item, "unit", "?")
                taxonomy = getattr(item, "taxonomy", "us-gaap")
                derived = getattr(item, "derived", False)
                warnings = getattr(item, "warnings", [])

                val_str = f"{val:>20,.0f}" if val is not None else f"{'None':>20s}"
                tag = f"  {metric_name:30s}  {val_str}  {unit:8s}"
                tag += f"  concept={taxonomy}:{concept}"
                tag += f"  fy={fy} fp={fp} form={form}"
                if derived:
                    components = getattr(item, "components", {})
                    tag += f"  [DERIVED from {list(components.keys())}]"
                if warnings:
                    tag += f"  WARN={warnings}"
                print(tag)

        print()


if __name__ == "__main__":
    asyncio.run(main())
