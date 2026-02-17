# Handoff

## Current State

Handspread is in a clean, testable state for core analysis flows:

- Engine orchestrates three concurrent streams and isolates failures per ticker
- EV bridge, multiples, growth, and operating metrics all carry provenance metadata
- Finnhub client has TTL cache and bounded concurrency
- Test suite runs offline and now includes scenario regressions for production cohorts
- Robustness contracts are documented in `ROBUSTNESS_SPEC.md`
- Growth is computed from LTM vs LTM-1 (not annual series)
- Multiples include both adjusted and GAAP EV/EBITDA variants

## Recently Landed (2026-02-17)

- Empty input guardrail: `analyze_comps([])` raises `ValueError`.
- Market quote guardrail: non-numeric/zero/negative price is treated as missing with warnings.
- Growth update: YoY now uses LTM vs LTM-1 values with safe handling for missing inputs.
- Currency guardrail:
  - EV bridge fails closed on non-USD SEC currency.
  - EV/equity mixed-currency multiples fail closed with warnings.
  - `revenue_per_share` unit follows SEC currency.
- EBITDA update:
  - `ev_ebitda` uses adjusted EBITDA (`OI + D&A + SBC`).
  - `ev_ebitda_gaap` remains available for the raw denominator.
  - Missing SBC produces warning-based fallback.
- Added scenario regression suite in `tests/test_scenario_regressions.py` covering:
  - Big Tech baseline
  - Financials
  - Negative-equity buyback names
  - REIT lease path
  - Pre-revenue/deep-loss names
  - Conglomerates
  - Foreign ADR currency stress
  - Chinese ADR CNY cluster

## Design Decisions To Preserve

- Keep provenance explicit in the data model. This is the main differentiator of the project.
- Keep errors isolated per ticker. Losing one company should not kill the run.
- Keep EV policy configurable and visible in call sites. This prevents hidden analyst-assumption drift.
- Keep market fallback assumptions paired with warnings. Silent unit guesses are hard to debug later.
- Keep currency boundaries fail-closed for mixed market/SEC arithmetic.

## Verification

Run these before merging or sharing results:

```bash
python -m pytest tests/ -x -v
ruff check .
ruff format --check .
```

## Runtime Requirements

Set these environment variables before running examples:

- `FINNHUB_API_KEY`
- `EDGARPACK_USER_AGENT`

Optional tuning:

- `MARKET_TTL_SECONDS` (default `300`, set `0` to disable cache reuse)
- `MARKET_CONCURRENCY` (default `8`)

## Suggested Next Work

- Continue scenario coverage on remaining open beads:
  - Delisted/acquired tickers and invalid symbols
  - Airlines lease-heavy basket
  - Mega-cap vs small-cap scale-mix stress
  - Oil & gas cyclicals
  - Biotech R&D-intensity basket
  - Large comp-set rate-limit behavior
- Add snapshot fixtures for known outputs to detect metric drift
- Add presentation-layer output formats once metric definitions are stable
