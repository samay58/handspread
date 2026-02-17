# CLAUDE.md

## What This Is

Handspread is a comparable company analysis engine with full provenance. It combines SEC EDGAR financial statement data from edgarpack with Finnhub market data. The engine runs three async streams in parallel and builds one `CompanyAnalysis` per ticker.

## Commands

```bash
# Install (editable)
uv pip install -e "../edgarpack"
uv pip install -e ".[dev]"

# Run tests (offline)
python -m pytest tests/ -x -v

# Lint + format check
ruff check . && ruff format --check .

# Run example (requires env vars)
FINNHUB_API_KEY=<key> EDGARPACK_USER_AGENT="Name email@example.com" python examples/run_comps.py
```

## Architecture

Three concurrent streams feed `handspread/engine.py`:

1. SEC LTM financials via `edgarpack.query.comps()`
2. SEC LTM-1 for growth via `edgarpack.query.comps(period="ltm-1")`
3. Finnhub market data via `handspread/market/finnhub_client.py`

`analyze_comps()` fans out those calls, applies a timeout, and builds each `CompanyAnalysis` with isolated per-company errors.

## Design Decisions

- We isolate failures per ticker and return partial output. The caller usually wants coverage across the full comp set, not all-or-nothing behavior.
- We keep provenance at the value layer, not in ad-hoc side metadata. This keeps traceability hard to lose during refactors.
- We keep EV assumptions explicit through `EVPolicy`. These assumptions vary by team and should be easy to inspect.
- We keep Finnhub fallback heuristics narrow and warning-backed. Ambiguous units are surfaced instead of silently trusted.

### Analysis Modules

- `handspread/analysis/_utils.py`: shared SEC value extraction, currency detection, and `compute_adjusted_ebitda` (used by multiples, operating, and growth)
- `handspread/analysis/enterprise_value.py`: EV bridge construction and policy handling
- `handspread/analysis/multiples.py`: EV and equity multiples plus yields
- `handspread/analysis/growth.py`: YoY growth from LTM vs LTM-1 plus margin deltas (gross, EBITDA, adjusted EBITDA)
- `handspread/analysis/operating.py`: operating ratios, margin computations (gross, EBITDA, net, FCF, adjusted EBITDA), revenue/share, and ROIC

### Provenance Model

- `MarketValue`: direct vendor value from Finnhub
- `CitedValue`: SEC filing value from edgarpack
- `ComputedValue`: derived value with formula and components

## API Notes

`analyze_comps()` signature:

- `tickers: list[str]`
- `period: str = "ltm"`
- `ev_policy: EVPolicy | None = None`
- `timeout: float = 60.0`
- `tax_rate: float = 0.21`

`tax_rate` is used in ROIC as `operating_income * (1 - tax_rate) / invested_capital`.

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `FINNHUB_API_KEY` | Yes | - | Finnhub API key |
| `EDGARPACK_USER_AGENT` | Yes | - | SEC EDGAR user agent |
| `MARKET_TTL_SECONDS` | No | `300` | Market cache TTL in seconds. `0` disables cache reuse |
| `MARKET_CONCURRENCY` | No | `8` | Max concurrent Finnhub API calls |

## Testing Notes

Tests use `SimpleNamespace` SEC stubs and mocked Finnhub client calls. They run offline and should not require API keys.
