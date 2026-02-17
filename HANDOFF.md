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

## Smoke Test Fixes (2026-02-16)

8-company stress test (NVDA, AAPL, DDOG, TSM, SBUX, RIVN, F, BABA) surfaced 4 issues. All resolved:

- **ADR market cap** (hs-0tf, P0): Finnhub client now prefers vendor-reported `marketCapitalization` from the profile endpoint. Falls back to `price * shares` if the vendor field is missing or non-positive. Fixes TSM and BABA market cap being 10x overstated.
- **Captive finance debt** (edgarpack-c1b, P1): edgarpack `total_debt` concept list now includes broader XBRL tags that capture consolidated debt for companies like Ford with captive finance subsidiaries.
- **Annual-only filer growth** (edgarpack-pek, P1): edgarpack LTM-1 for 20-F filers (no quarterly data) now returns the prior fiscal year instead of the same year. TSM and BABA now show real YoY growth.
- **Stock split contamination** (edgarpack-6e6, P2): edgarpack attaches a split contamination warning when per-share LTM values differ from annual by more than 5x. Handspread growth computation skips those metrics and returns `value=None`.

Regression tests added in both projects. Full results in `docs/SMOKE-TEST-2026-02-16.md`.

## Design Decisions To Preserve

- Provenance stays explicit in the data model. Main differentiator of the project.
- Errors stay isolated per ticker. Losing one company should not kill the run.
- EV policy stays configurable and visible in call sites. Prevents hidden analyst-assumption drift.
- Market fallback assumptions stay paired with warnings. Silent unit guesses are hard to debug later.
- Currency boundaries stay fail-closed for mixed market/SEC arithmetic.

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
