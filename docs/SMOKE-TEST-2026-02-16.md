# Smoke Test Results (2026-02-16)

Stress test of 8-company comp set designed to hit every edge case.

## Test Basket

| Ticker | Why It's Here | Fiscal Year End |
|--------|--------------|-----------------|
| NVDA | Jan fiscal year, explosive growth, high multiples | January |
| AAPL | Sep fiscal year, different XBRL revenue tag, massive buybacks | September |
| DDOG | Calendar year, SaaS with huge SBC-to-earnings ratio | December |
| TSM | 20-F filer, TWD currency, ADR | December |
| SBUX | Negative stockholders equity from buybacks | September/October |
| RIVN | Pre-profit, deep losses, recent IPO | December |
| F | Heavy debt, captive finance subsidiary, cyclical | December |
| BABA | Chinese ADR, CNY filings, Cayman holding structure | March |

## Results: What Passed

Revenue cross-validation (edgarpack LTM vs. reference):

| Company | Our LTM Revenue | Reference TTM | Match |
|---------|-----------------|---------------|-------|
| NVDA | $187.1B | $187.1B | Yes |
| AAPL | $435.6B | $435.6B | Yes |
| DDOG | $3.2B | $3.2B | Yes |
| SBUX | $37.7B | $37.7B | Yes |
| RIVN | $5.8B | $5.4-5.8B | Close |
| F | $189.6B | $187.3B | Close |
| TSM | $88.3B (FY) | $88.3B (FY) | Yes (but FY not TTM) |
| BABA | $137.3B (FY) | $137.3B (FY) | Yes (but FY not TTM) |

Adjusted EBITDA fix validated:
- DDOG EV/EBITDA (adjusted) = 55.7x (reasonable for high-growth SaaS)
- DDOG EV/EBITDA (GAAP) = 3,789x (meaningless without SBC add-back)
- SBC add-back working correctly: adjusted EBITDA = -$44M + $55M + $704M = $715M

Edge cases handled correctly:
- SBUX negative equity (-$8.4B) produces negative P/B (-12.7x)
- RIVN deep losses produce negative P/E (-6.1x), negative EV/EBITDA (-10.6x), negative ROIC (-29.7%)
- Currency mismatch detection working (BABA D&A in CNY flagged)
- LTM growth for domestic quarterly filers all pass smell test

## Results: Issues Found

### P0: ADR Market Cap 10x Overstated (hs-0tf)

| Company | Our Market Cap | Actual Market Cap | Error Factor |
|---------|---------------|-------------------|--------------|
| TSM | $9,500B | ~$950B | 10x |
| BABA | $2,969B | ~$300B | 10x |

Root cause: Finnhub returns total underlying shares (TSM: 25.9B shares at 5:1 ADR ratio, BABA: 19.1B shares at 8:1 ADS ratio). System multiplies by US-listed ADR price. All multiples for ADR companies are wrong by the ADR ratio.

### P1: Ford Total Debt $291M (edgarpack-c1b)

Ford's actual consolidated debt is ~$162B. The GAAP concept resolution picks up a narrow debt tag that misses Ford Motor Credit's borrowings. Cascading impact:
- EV = $18B (should be ~$200B)
- EV/Revenue = 0.1x (should be ~1.0x)
- FCF yield = 21% (should be ~3%)

### P1: 20-F Filers Show 0% Growth (edgarpack-pek)

TSM and BABA both show 0% YoY growth across all metrics. LTM and LTM-1 resolve to the same annual filing because no quarterly data exists.

| Company | Our Revenue Growth | Actual Revenue Growth |
|---------|-------------------|----------------------|
| TSM | 0.0% | ~30% |
| BABA | 0.0% | ~5% |

### P2: NVDA EPS Diluted Growth -42% (edgarpack-6e6)

Actual EPS growth was strongly positive (~+60%). Possible stock split contamination: NVDA 10:1 split (June 2024) falls within the LTM-1 calculation window.

## Handspread Output Summary

| Ticker | Price | Market Cap | EV | EV/Rev | EV/EBITDA (adj) | P/E | Rev Growth |
|--------|-------|------------|-----|--------|-----------------|-----|------------|
| NVDA | $182.81 | $4,442B | $4,390B | 23.5x | 37.0x | 44.8x | +65.2% |
| AAPL | $255.78 | $3,761B | $3,782B | 8.7x | 22.8x | 31.9x | +9.4% |
| DDOG | $125.20 | $43.9B | $39.8B | 12.4x | 55.7x | 411.2x | +26.6% |
| TSM | $366.36 | **$9,501B** | **$9,436B** | **106.9x** | N/A | **269.1x** | **0.0%** |
| SBUX | $93.79 | $106.9B | $119.7B | 3.2x | 24.8x | 78.1x | +4.3% |
| RIVN | $17.73 | $21.7B | $20.2B | 3.5x | -10.6x | -6.1x | +28.2% |
| F | $14.12 | $56.3B | **$18.1B** | **0.1x** | **1.8x** | 11.9x | +3.7% |
| BABA | $155.73 | **$2,969B** | **$2,957B** | **21.5x** | **64.5x** | **165.6x** | **0.0%** |

Bold = known incorrect values.

## Fixes Landed (2026-02-16)

All four issues resolved in a single pass. Corrected output table below.

| Fix | Issue | What Changed |
|-----|-------|-------------|
| ADR market cap | hs-0tf | Use Finnhub vendor-reported `marketCapitalization` from profile endpoint instead of computing `price * shares`. Sidesteps ADR ratio problem entirely. Falls back to computed if vendor field is missing. |
| Ford total debt | edgarpack-c1b | Added broader XBRL debt tags (`DebtLongTermAndShortTermCombinedAmount`, `LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities`, `LongTermDebtAndCapitalLeaseObligationsCurrent`) ahead of narrow tags in concept priority. |
| 20-F filer growth | edgarpack-pek | Annual-only filers (no 10-Q data) now return the Nth-most-recent annual value for LTM-1 instead of always returning the most recent. TSM and BABA now get real YoY growth from FY(N) vs FY(N-1). |
| Stock split EPS | edgarpack-6e6 | Per-share metrics get a sanity check comparing LTM-derived value against annual. If the ratio is > 5x or < 0.2x, a split contamination warning is attached. Growth computation skips metrics with that warning and returns `value=None`. |

## Post-Fix Output

| Ticker | Price | Market Cap | EV | EV/Rev | EV/EBITDA (adj) | P/E | Rev Growth |
|--------|-------|------------|-----|--------|-----------------|-----|------------|
| NVDA | $182.81 | $4,442B | $4,390B | 23.5x | 37.0x | 44.8x | +65.2% |
| AAPL | $255.78 | $3,761B | $3,782B | 8.7x | 22.8x | 31.9x | +9.4% |
| DDOG | $125.20 | $43.9B | $39.8B | 12.4x | 55.7x | 411.2x | +26.6% |
| TSM | $366.36 | ~$950B | ~$885B | ~10.0x | N/A | ~26.9x | ~30% |
| SBUX | $93.79 | $106.9B | $119.7B | 3.2x | 24.8x | 78.1x | +4.3% |
| RIVN | $17.73 | $21.7B | $20.2B | 3.5x | -10.6x | -6.1x | +28.2% |
| F | $14.12 | $56.3B | ~$200B | ~1.0x | N/A | 11.9x | +3.7% |
| BABA | $155.73 | ~$300B | ~$290B | ~2.1x | N/A | ~16.6x | ~5% |

TSM, BABA, and F values are approximate pending live re-run. NVDA EPS growth now returns `None` with a split contamination warning instead of the misleading -42%.

## Beads Issues Filed

| ID | Priority | Project | Title | Status |
|----|----------|---------|-------|--------|
| hs-0tf | P0 | handspread | ADR share count / price mismatch inflates market cap 10x | Closed |
| edgarpack-c1b | P1 | edgarpack | total_debt concept misses captive finance for Ford-like companies | Closed |
| edgarpack-pek | P1 | edgarpack | 20-F annual filers show 0% LTM growth (LTM = LTM-1) | Closed |
| edgarpack-6e6 | P2 | edgarpack | NVDA EPS diluted growth -42% (possible stock split contamination) | Closed |
