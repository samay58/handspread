# Handspread

Comparable company analysis engine with full provenance chains. Every number traces back to its source: SEC EDGAR filings (via edgarpack) or market data vendor (Finnhub).

## Install

```bash
# From the handspread directory
uv pip install -e "../edgarpack"
uv pip install -e ".[dev]"
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `FINNHUB_API_KEY` | Yes | - | Finnhub API key |
| `EDGARPACK_USER_AGENT` | Yes | - | SEC EDGAR user agent (e.g. "Company admin@co.com") |
| `MARKET_TTL_SECONDS` | No | 300 | Market data cache TTL |
| `MARKET_CONCURRENCY` | No | 8 | Max concurrent Finnhub requests |

## Usage

```python
import asyncio
from handspread import analyze_comps

results = asyncio.run(analyze_comps(["NVDA", "AMD", "INTC"]))

for r in results:
    print(f"{r.company_name}: EV/Revenue = {r.multiples['ev_revenue'].value:.1f}x")
```

## Provenance Chain

Every value in a `CompanyAnalysis` is one of three types:

- **MarketValue**: from Finnhub, with vendor, endpoint, timestamp, and optional raw payload
- **CitedValue**: from SEC EDGAR (via edgarpack), with filing URL, accession number, XBRL concept
- **ComputedValue**: derived from other values, with formula string and component references

```python
ev_rev = results[0].multiples["ev_revenue"]
print(ev_rev.formula)       # "enterprise_value / revenue"
print(ev_rev.components)    # {"numerator": ComputedValue(...), "denominator": CitedValue(...)}
```

## Tests

```bash
python -m pytest tests/ -x -q
```

All tests are offline (no API keys needed). They use `SimpleNamespace` stubs for SEC data.

## Architecture

Three concurrent data streams feed into per-company analysis:

1. **SEC LTM financials** via `edgarpack.comps()` - income statement, balance sheet, cash flow
2. **SEC annual series** via `edgarpack.comps(period="annual:2")` - for YoY growth
3. **Finnhub market data** - price, shares outstanding, market cap

Each company gets: EV bridge, valuation multiples, growth rates, operating efficiency metrics.
