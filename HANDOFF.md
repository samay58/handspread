# Handoff

## Current State

Handspread is in a clean, testable state for core analysis flows:

- Engine orchestrates three concurrent streams and isolates failures per ticker
- EV bridge, multiples, growth, and operating metrics all carry provenance metadata
- Finnhub client has TTL cache and bounded concurrency
- Test suite runs offline and covers core edge cases

## Design Decisions To Preserve

- Keep provenance explicit in the data model. This is the main differentiator of the project.
- Keep errors isolated per ticker. Losing one company should not kill the run.
- Keep EV policy configurable and visible in call sites. This prevents hidden analyst-assumption drift.
- Keep market fallback assumptions paired with warnings. Silent unit guesses are hard to debug later.

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

- Add sector baseline regression tests for larger ticker baskets
- Add snapshot fixtures for known outputs to detect metric drift
- Add presentation-layer output formats once metric definitions are stable
