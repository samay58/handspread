# Robustness Spec (2026-02-17)

## Scope

This iteration resolves and hardens:

- `hs-hgv`: Currency mismatch corrupts equity multiples and per-share labeling.
- `hs-y44`: Empty ticker list should not silently succeed.
- `hs-17w`: Non-positive / malformed quote price should not produce fake market cap.
- `hs-d97`: Growth with missing values should not crash or mis-index.
- `hs-l81`: Growth basis switched to LTM vs LTM-1.
- `hs-4h6`: SBC add-back added for adjusted EBITDA.
- Regression coverage tasks: `hs-zzu`, `hs-4en`, `hs-fsu`, `hs-s6o`, `hs-3l4`, `hs-zyw`, `hs-7c1`, `hs-i35`.

## Design Principles

- Fail closed for invalid cross-currency arithmetic.
- Keep computations available when mathematically valid (for example SEC-only ratios).
- Prefer small, shared guardrail helpers over one-off conditionals.
- Keep tests deterministic and offline by mocking upstream providers.

## Behavioral Contracts

1. Engine input contract
- `analyze_comps([])` raises `ValueError` with a clear message.

2. Market price contract
- Quote price must be numeric and strictly positive.
- Invalid price (`None`, non-numeric, `<= 0`) is treated as missing with warnings.
- Market cap is only computed when both price and shares are valid.

3. Growth series contract
- Growth uses LTM and LTM-1 values.
- Missing LTM or LTM-1 values yield no growth metric, never an exception.

4. Adjusted EBITDA contract
- `adjusted_ebitda = operating_income + depreciation_amortization + stock_based_compensation`.
- `ev_ebitda` uses adjusted EBITDA as denominator.
- `ev_ebitda_gaap` remains available using raw `ebitda`.
- If SBC is missing but OI and D&A exist, adjusted EBITDA still computes with warning.

5. Currency boundary contract
- Market value inputs (`price`, `market_cap`) are USD.
- Any metric mixing USD market value with non-USD SEC value returns `None` and a warning.
- This applies to EV-based multiples, P/E, P/B, FCF yield, and dividend yield.
- SEC-only operating ratios remain computable for non-USD reporters.
- `revenue_per_share` unit is derived from SEC currency (`USD/shares`, `JPY/shares`, etc.), not hardcoded.

## Implementation Outline

1. Add shared helpers in `handspread/analysis/_utils.py` for:
- SEC currency detection.
- Cross-currency guard message generation.

2. Update `handspread/analysis/multiples.py`:
- Add adjusted EBITDA computation and `ev_ebitda_gaap`.
- Gate mixed USD/non-USD metrics before division.
- Return structured `ComputedValue` with warning when blocked.

3. Update `handspread/analysis/operating.py`:
- Derive `revenue_per_share` unit from SEC currency.
- Add warning when non-USD SEC revenue is paired with market share count context.

4. Update `handspread/analysis/growth.py`:
- Compute YoY from LTM vs LTM-1 values with safe missing-value handling.

5. Update `handspread/engine.py` and `handspread/market/finnhub_client.py`:
- Add empty-input validation.
- Harden quote price parsing/validation.
- Fetch LTM-1 metrics for growth stream.

## Test Plan

- Add targeted unit tests per bug contract.
- Add scenario-style regression tests for the six ticker cohorts with mocked SEC/market data and policy variants.
- Run full suite + lint + format checks before close.

## Landed Test Coverage

Unit-level contract tests:

- `tests/test_engine.py`: empty ticker list validation.
- `tests/test_finnhub_client.py`: non-numeric and non-positive price handling.
- `tests/test_growth.py`: LTM vs LTM-1 growth correctness and missing-input safety.
- `tests/test_multiples.py`: adjusted EBITDA behavior plus mixed-currency blocking for market/SEC ratios.
- `tests/test_operating.py`: SEC-currency unit propagation for `revenue_per_share`.

Scenario-level regressions:

- `tests/test_scenario_regressions.py`
  - Big Tech baseline (`hs-zzu`)
  - Banks/financials (`hs-4en`)
  - Negative-equity buyback names (`hs-fsu`)
  - REIT lease path (`hs-s6o`)
  - Pre-revenue/deep-loss names (`hs-3l4`)
  - Conglomerates/complex structures (`hs-zyw`)
  - Foreign ADR multi-currency stress (`hs-7c1`)
  - Chinese ADR CNY cluster (`hs-i35`)
