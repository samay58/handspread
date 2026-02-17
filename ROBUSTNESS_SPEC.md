# Robustness Spec (2026-02-17)

## Scope

This iteration resolves and hardens:

- `hs-hgv`: Currency mismatch corrupts equity multiples and per-share labeling.
- `hs-y44`: Empty ticker list should not silently succeed.
- `hs-17w`: Non-positive / malformed quote price should not produce fake market cap.
- `hs-d97`: Growth series with `None` entries should not crash or mis-index.
- Regression coverage tasks: `hs-zzu`, `hs-4en`, `hs-fsu`, `hs-s6o`, `hs-3l4`, `hs-zyw`.

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
- Growth uses the first two valid entries from a series (ignores `None` elements).
- Missing usable pair yields no growth value, never an exception.

4. Currency boundary contract
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
- Gate mixed USD/non-USD metrics before division.
- Return structured `ComputedValue` with warning when blocked.

3. Update `handspread/analysis/operating.py`:
- Derive `revenue_per_share` unit from SEC currency.
- Add warning when non-USD SEC revenue is paired with market share count context.

4. Update `handspread/analysis/growth.py`:
- Sanitize lists by filtering `None` entries before YoY extraction.

5. Update `handspread/engine.py` and `handspread/market/finnhub_client.py`:
- Add empty-input validation.
- Harden quote price parsing/validation.

## Test Plan

- Add targeted unit tests per bug contract.
- Add scenario-style regression tests for the six ticker cohorts with mocked SEC/market data and policy variants.
- Run full suite + lint + format checks before close.
