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
- EV and equity multiples: EV/Revenue, EV/EBITDA (adjusted), EV/EBITDA (GAAP), EV/EBIT, EV/FCF, P/E, P/B, FCF yield, dividend yield
- Adjusted EBITDA: `operating_income + depreciation_amortization + stock_based_compensation`
- YoY growth from LTM vs LTM-1 SEC data
- Operating metrics: R&D %, SG&A %, capex %, revenue per share, ROIC

## Design Choices

- We run three independent data streams in parallel. That keeps runs fast and keeps one slow upstream from blocking everything.
- We isolate failures per ticker. A bad ticker should not break the whole comp set.
- We model every value as `MarketValue`, `CitedValue`, or `ComputedValue`. This keeps audit trails explicit in code, not buried in comments.
- We keep EV policy choices configurable. Different teams treat leases, debt splits, and non-operating assets differently, so we make those choices visible and repeatable.
- We treat ambiguous market-unit edge cases conservatively and attach warnings. It is better to flag uncertainty than quietly publish a clean-looking bad number.

## Robustness Contracts

- `analyze_comps([])` raises `ValueError` instead of silently returning `[]`.
- Finnhub quote price must be numeric and strictly positive. Invalid values are treated as missing with warnings.
- Market cap is only computed when both price and shares are valid.
- Growth calculations require both LTM and LTM-1 values; missing values are skipped safely.
- Currency mismatches fail closed:
  - EV bridge returns `None` when SEC currency is non-USD.
  - EV multiples, equity multiples, FCF yield, and dividend yield return `None` for cross-currency mixes.
  - `revenue_per_share` unit follows SEC currency (for example `JPY/shares`) and includes a warning when market context is USD.
- Adjusted EBITDA contract:
  - `ev_ebitda` uses adjusted EBITDA (`OI + D&A + SBC`) as denominator.
  - `ev_ebitda_gaap` preserves the raw GAAP EBITDA denominator.
  - If SBC is missing, adjusted EBITDA still computes with a warning.

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

## Regression Coverage

- Targeted unit tests for robustness contracts:
  - `tests/test_engine.py`
  - `tests/test_finnhub_client.py`
  - `tests/test_growth.py`
  - `tests/test_multiples.py`
  - `tests/test_operating.py`
- Scenario regression suite for production cohorts:
  - `tests/test_scenario_regressions.py`
  - Covers Big Tech baseline, financials, negative-equity buyback names, REIT lease path, deep-loss/pre-revenue names, conglomerates, foreign ADR currency stress, and Chinese ADR CNY behavior.

## More Detail

- `ARCHITECTURE.md`: plain-language walkthrough for technical and non-technical readers
- `ROBUSTNESS_SPEC.md`: explicit guardrail spec and test plan for robustness behavior
- `handspread/CLAUDE.md`: engineering context and commands for contributors
