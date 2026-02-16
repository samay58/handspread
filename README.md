# Handspread

Handspread builds comparable company analysis from primary sources. Market data comes from Finnhub. Financial statement data comes from SEC EDGAR filings via edgarpack. Every computed number keeps its source chain.

## Quickstart

```bash
uv pip install -e "../edgarpack"
uv pip install -e ".[dev]"

FINNHUB_API_KEY=<your-key> \
EDGARPACK_USER_AGENT="Name email@co.com" \
python examples/run_comps.py
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `FINNHUB_API_KEY` | Yes | - | Finnhub API key |
| `EDGARPACK_USER_AGENT` | Yes | - | SEC EDGAR user agent, for example `Name email@co.com` |
| `MARKET_TTL_SECONDS` | No | `300` | Market payload cache TTL in seconds. `0` disables cache reuse |
| `MARKET_CONCURRENCY` | No | `8` | Max concurrent Finnhub calls |

## Usage

```python
import asyncio

from handspread import analyze_comps

results = asyncio.run(
    analyze_comps(
        ["NVDA", "AMD", "INTC"],
        period="ltm",
        tax_rate=0.21,
    )
)

for r in results:
    ev_rev = r.multiples.get("ev_revenue")
    if ev_rev and ev_rev.value is not None:
        print(f"{r.symbol}: EV/Revenue {ev_rev.value:.1f}x")
```

## What It Computes

- EV bridge with configurable policy choices for debt, cash, leases, and investment adjustments
- EV and equity multiples: EV/Revenue, EV/EBITDA, EV/EBIT, EV/FCF, P/E, P/B, FCF yield, dividend yield
- YoY growth from annual series
- Operating metrics: R&D %, SG&A %, capex %, revenue per share, ROIC

## Provenance Model

Every value in `CompanyAnalysis` is one of these types:

- `MarketValue`: direct vendor datapoint, with endpoint and fetch timestamp
- `CitedValue`: SEC filing datapoint from edgarpack, with filing metadata
- `ComputedValue`: derived value with formula text and component references

## Quality Checks

```bash
python -m pytest tests/ -x -v
ruff check .
ruff format --check .
```

## More Detail

- `ARCHITECTURE.md`: plain-language walkthrough for technical and non-technical readers
- `handspread/CLAUDE.md`: engineering context and commands for contributors
