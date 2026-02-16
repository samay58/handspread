# CLAUDE.md

## What This Is

Handspread is a comparable company analysis engine that produces fully-provenanced financial analysis. Every number in the output traces back to its source: SEC EDGAR filings (via edgarpack's XBRL extraction) or Finnhub market data. The engine runs three concurrent data streams (SEC LTM financials, SEC annual series, Finnhub market data) and assembles per-company analysis objects containing EV bridges, valuation multiples, growth rates, and operating metrics.

## Commands

```bash
# Install (editable, with dev deps)
uv pip install -e "../edgarpack"
uv pip install -e ".[dev]"

# Run all tests (offline, no API keys needed)
python -m pytest tests/ -x -v

# Lint + format
ruff check . && ruff format --check .

# Run example (requires env vars)
FINNHUB_API_KEY=<key> EDGARPACK_USER_AGENT="Name email@example.com" python examples/run_comps.py
```

## Architecture

Three concurrent async data streams feed `engine.py`:

1. **SEC LTM financials** via `edgarpack.query.comps()` for income statement, balance sheet, cash flow
2. **SEC annual series** via `edgarpack.query.comps(period="annual:2")` for YoY growth calculations
3. **Finnhub market data** via `market/finnhub_client.py` for price, shares outstanding, market cap

Each company gets assembled into a `CompanyAnalysis` by `_build_single()`. Failures are isolated per-company (errors list, not exceptions).

### Analysis modules (`analysis/`)

- `_utils.py` - Shared `extract_sec_value()` helper for extracting values from SEC metrics dicts
- `enterprise_value.py` - EV bridge construction with configurable `EVPolicy` (debt modes, cash treatment, lease/preferred/NCI adjustments)
- `multiples.py` - EV-based (EV/Revenue, EV/EBITDA, EV/EBIT, EV/FCF) and equity-based (P/E, P/B, FCF yield, dividend yield) multiples
- `growth.py` - YoY growth from annual series data
- `operating.py` - Efficiency ratios (R&D/revenue, SG&A/revenue, capex/revenue, revenue/share, ROIC)

### Provenance chain

Every value is one of three types:
- `MarketValue` - from Finnhub, with vendor, endpoint, timestamp
- `CitedValue` - from SEC EDGAR, with filing URL, accession number, XBRL concept
- `ComputedValue` - derived, with formula string and component references

## Key Design Decisions

- **Why Finnhub**: 60 calls/min free tier, real-time prices, profile data with company name. Cached at module level with TTL.
- **Why async**: Three independent data streams (two SEC, one market) run concurrently via `asyncio.gather` with a configurable timeout (default 60s).
- **Why EVPolicy is configurable**: Different analysts treat debt, cash, leases, and minority interests differently. The policy object makes these choices explicit and auditable.
- **Stdlib-first via edgarpack**: The SEC data layer (edgarpack) uses no external HTTP libs. Handspread adds only `finnhub-python` and `pydantic-settings`.

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `FINNHUB_API_KEY` | Yes | - | Finnhub API key (free tier: finnhub.io) |
| `EDGARPACK_USER_AGENT` | Yes | - | SEC EDGAR user agent ("Company admin@co.com") |
| `MARKET_TTL_SECONDS` | No | 300 | Market data cache TTL in seconds |
| `MARKET_CONCURRENCY` | No | 8 | Max concurrent Finnhub API calls |

## Testing

All tests are offline (no API keys needed). They use `SimpleNamespace` stubs for SEC `CitedValue` objects and `unittest.mock` for the Finnhub client. All timestamps are UTC.

Test files: `test_engine.py`, `test_finnhub_client.py`, `test_enterprise_value.py`, `test_multiples.py`, `test_growth.py`, `test_operating.py`, `test_models.py`.
