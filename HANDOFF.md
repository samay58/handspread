# Handspread: Professional Comparable Company Analysis Engine

You are building **handspread**, a Python project that produces professional-grade comparable company analysis ("comps") at the quality level of an investment banking analyst handspreading financials. The system combines SEC filing data (via edgarpack) with real-time market data (via Finnhub) to compute a full set of valuation and operating metrics, where every number is auditable and traceable to its source.

This document gives you full context on the two upstream projects, the gap analysis, and the design approach. Read it completely before writing any code.

## Project Location

```
~/Projects/active/handspread/
```

## What "Handspreading" Means

In investment banking, "handspreading" is the manual process of pulling financial data from SEC filings (10-K, 10-Q), entering it into a spreadsheet, computing valuation multiples, and comparing companies side by side. A good handspread:

- Pulls data directly from primary sources (SEC filings, not aggregator databases)
- Computes every metric from its components (EBITDA = operating income + D&A, not a pre-computed number someone gave you)
- Makes every number auditable (you can trace revenue back to the exact 10-K, the exact XBRL tag, the exact filing date)
- Uses consistent methodology across all companies in the comp set (same fiscal period basis, same metric definitions)
- Includes both operating metrics (margins, growth rates) and valuation multiples (EV/Revenue, EV/EBITDA, P/E)

Handspread automates this process while preserving the auditability and rigor that makes it valuable.

## Scope of This Phase

**In scope:** The analysis engine. Pull the right data, compute the full metric set, maintain full provenance on every number.

**Out of scope (deferred):**
- Output formatting (Excel, PDF, HTML). Comes next.
- Comp set selection (picking the right peer group). Being worked on separately.
- LLM-generated commentary or narrative. This is a quantitative engine.

The company list is an **input** to the system, not something it needs to figure out. Assume you'll receive a list of tickers like `["NVDA", "AMD", "INTC", "AVGO", "QCOM"]`.

---

## Upstream Project 1: edgarpack

**Location:** `~/Projects/active/edgarpack`
**What it is:** A Python library that transforms SEC EDGAR filings into clean, section-addressable markdown packs. More relevant for handspread: it has a query layer that pulls cited financial metrics directly from SEC XBRL data.

### How to Use It

Install as an editable dependency:

```bash
pip install -e ~/Projects/active/edgarpack
```

Then import the query layer:

```python
from edgarpack.query import financials, comps, CitedValue, DerivedValue, QueryResult
```

### The Query API

Two async functions are the core interface:

**Single company:**
```python
async def financials(
    company: str,                        # Ticker ("NVDA") or CIK ("1045810")
    metrics: str | list[str] | None = None,  # "revenue", ["revenue", "net_income"], or None for all
    period: str = "lfy",                 # Period selector (see below)
    force: bool = False,                 # Bypass cache
) -> QueryResult
```

**Multiple companies (runs in parallel via asyncio.gather):**
```python
async def comps(
    companies: list[str],    # ["NVDA", "AMD", "INTC"]
    metrics: list[str],      # ["revenue", "net_income", "gross_margin"]
    period: str = "lfy",
    force: bool = False,
) -> dict[str, QueryResult]  # Keyed by company identifier
```

### Period Selectors

| Selector | What It Returns | Use Case |
|----------|----------------|----------|
| `lfy` | Last fiscal year (most recent 10-K) | Annual comparisons |
| `mrq` | Most recent quarter (standalone 3-month) | Latest quarterly performance |
| `mrp` | Most recent period (whatever filed last) | Freshest data point |
| `ltm` | Last twelve months (trailing, computed) | Cross-calendar comparisons |
| `annual:N` | Last N fiscal years | Multi-year trends |
| `quarterly:N` | Last N quarters | Quarterly trends |

**LTM computation** for P&L/cash flow metrics:
```
LTM = MRP_cumulative + LFY_annual - MRP_prior_year_cumulative
```
For balance sheet metrics, LTM returns the most recent reported value.

### Data Models

Every value from edgarpack carries full provenance:

```python
class CitedValue(BaseModel):
    value: float | int | None
    unit: str              # "USD", "shares", "USD/shares", "pure"
    metric: str            # Normalized name: "revenue", "eps_diluted"
    concept: str           # Actual XBRL tag used: "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"

    # Period
    period_start: date | None
    period_end: date
    fiscal_year: int
    fiscal_period: str     # "FY", "Q1", "Q2", "Q3", "Q4"

    # Source
    form_type: str         # "10-K", "10-Q"
    filed: date
    accession: str         # SEC accession number
    cik: str
    company: str

    # Computed properties
    filing_url -> str      # Full SEC EDGAR URL
    citation -> str        # "NVIDIA CORP 10-K (FY2025), filed 2025-02-18"
```

**DerivedValue** extends CitedValue for computed metrics (margins, EBITDA, FCF):
```python
class DerivedValue(CitedValue):
    derived: bool = True
    components: dict[str, CitedValue]  # The source values used in computation
```

**QueryResult** wraps a single company's metrics:
```python
class QueryResult(BaseModel):
    company: str
    cik: str
    period: str
    metrics: dict[str, CitedValue | list[CitedValue] | None]

    permalink -> str       # CLI command to reproduce: "edgarpack query 0001045810 revenue --period lfy"
    to_lean_dict() -> dict # JSON with deduplicated filings, auto-included components
    to_cited_dict() -> dict # Full provenance on every value
```

### Available Metrics (33 total)

**Income Statement (duration):**
`revenue`, `cost_of_revenue`, `gross_profit`, `operating_income`, `net_income`, `eps_basic`, `eps_diluted`, `rd_expense`, `sga_expense`, `depreciation_amortization`

**Balance Sheet (instant):**
`total_assets`, `current_assets`, `total_liabilities`, `current_liabilities`, `stockholders_equity`, `cash`, `total_debt`, `short_term_debt`, `marketable_securities`, `inventory`, `accounts_receivable`, `accounts_payable`

**EV Bridge (instant):**
`short_term_debt`, `marketable_securities`, `operating_lease_liabilities`, `noncontrolling_interests`, `preferred_stock`, `equity_method_investments`

**Cash Flow (duration):**
`operating_cash_flow`, `capex`

**Per Share:**
`shares_outstanding`, `shares_diluted`, `dividends_per_share`

**Derived (computed from components):**
| Metric | Formula | Unit |
|--------|---------|------|
| `ebitda` | operating_income + depreciation_amortization | USD |
| `free_cash_flow` | operating_cash_flow - capex | USD |
| `working_capital` | current_assets - current_liabilities | USD |
| `gross_margin` | gross_profit / revenue | pure (ratio) |
| `operating_margin` | operating_income / revenue | pure |
| `net_margin` | net_income / revenue | pure |
| `roe` | net_income / stockholders_equity | pure |
| `roa` | net_income / total_assets | pure |
| `current_ratio` | current_assets / current_liabilities | pure |
| `debt_to_equity` | total_debt / stockholders_equity | pure |
| `ebitda_margin` | ebitda / revenue | pure (ratio) |
| `fcf_margin` | free_cash_flow / revenue | pure (ratio) |

### Concept Resolution

Different companies use different XBRL tags for the same thing. Apple reports revenue as `RevenueFromContractWithCustomerExcludingAssessedTax`; NVIDIA uses `Revenues`. EdgarPack's concept resolver handles this:

1. Looks up the metric in a priority-ordered concept map (e.g., "revenue" maps to 6 possible GAAP tags)
2. Checks which concepts exist in the company's XBRL data
3. Scores by recency (highest fiscal year among annual entries wins)
4. Falls back to IFRS taxonomy for non-US filers (20-F)

This means `financials("AAPL", "revenue")` and `financials("NVDA", "revenue")` both work correctly, and you know exactly which XBRL tag resolved for each.

### Derived Metric Safeguards

- Cross-year validation: if numerator and denominator come from different fiscal years, returns None
- Division by zero: returns None
- Missing component: returns None for the entire derived metric
- Recursive: EBITDA resolves operating_income and D&A independently

### JSON Output Formats

**Lean format** (optimized for downstream consumption):
```json
{
  "company": "NVIDIA CORP",
  "cik": "0001045810",
  "period": "lfy",
  "permalink": "edgarpack query 0001045810 revenue,gross_margin --period lfy",
  "filings": {
    "0001045810-25-000001": {
      "form_type": "10-K",
      "filed": "2025-02-18",
      "fiscal_year": 2025,
      "fiscal_period": "FY",
      "url": "https://www.sec.gov/Archives/edgar/data/1045810/..."
    }
  },
  "metrics": {
    "revenue": {
      "value": 60922000000,
      "unit": "USD",
      "concept": "Revenues",
      "period": "2024-01-29/2025-01-26",
      "accession": "0001045810-25-000001"
    },
    "gross_margin": {
      "value": 0.7355,
      "unit": "pure",
      "concept": "gross_profit / revenue",
      "period": "2024-01-29/2025-01-26",
      "accession": "0001045810-25-000001",
      "derived": true,
      "formula": "gross_profit / revenue",
      "components": ["gross_profit", "revenue"]
    }
  }
}
```

### What EdgarPack Does NOT Have

These are the gaps handspread needs to fill:

1. **No market data.** No stock price, no market cap, no enterprise value. EdgarPack only touches SEC filings.
2. **No valuation multiples.** No EV/Revenue, EV/EBITDA, P/E. These require combining market data with SEC data.
3. **No growth rates.** No YoY revenue growth, margin expansion/contraction. The raw data is there (via `annual:N`), but the computation isn't.
4. **No enterprise value computation.** EdgarPack now provides all the balance sheet building blocks for the EV bridge (debt, cash, marketable securities, lease liabilities, NCI, preferred stock), but the assembly logic (Market Cap + Debt - Cash + adjustments) belongs in handspread where it can handle missing data and apply consistent treatment choices across the comp set.

---

## Upstream Project 2: massive-eval

**Location:** `~/massive-eval`
**What it is:** An evaluation of market data APIs for pulling equity price and shares outstanding. Tested three sources head-to-head: Massive (Polygon.io), Finnhub, and yfinance.

### The Verdict

**Use Finnhub** as the market data source.

| Source | Rate Limit (Free) | Latency (2 tickers) | Reliability |
|--------|-------------------|---------------------|-------------|
| Massive (Polygon) | 5 calls/min | ~13.5s (rate-limited) | Production API, but overkill |
| **Finnhub** | **60 calls/min** | **~900ms** | **Production API with SLA** |
| yfinance | Unthrottled | ~730ms | Unofficial scraping, can break |

### Finnhub API Details

**SDK:** `finnhub-python` (pip install finnhub-python)
**Auth:** API key (free tier, sign up at finnhub.io)
**Rate limit:** 60 calls/min on free tier

**Two endpoints needed:**

```python
import finnhub

client = finnhub.Client(api_key="YOUR_KEY")

# Current stock price
quote = client.quote("NVDA")
price = quote["c"]  # Current price

# Shares outstanding (returned in MILLIONS, multiply by 1_000_000)
profile = client.company_profile2(symbol="NVDA")
shares = profile["shareOutstanding"] * 1_000_000
company_name = profile["name"]
market_cap_from_finnhub = profile["marketCapitalization"]  # Also in millions
```

**Per ticker:** 2 API calls (quote + profile)
**For 10 companies:** 20 calls, well within 60/min

### Cross-Validation Results (from massive-eval)

All three sources agreed on shares outstanding for NVDA and AMD. Price differences were immaterial ($0.03 on a $182 stock, previous close vs. last trade). The data is reliable.

### What massive-eval Teaches

- Finnhub is the right default for free-tier market data
- 2 calls per ticker covers price + shares outstanding
- Shares outstanding from Finnhub is in millions (conversion needed)
- For SEC-sourced fundamentals beyond what XBRL provides, FMP at $22/mo is the paid fallback
- yfinance works for prototyping but is not production-safe

---

## The Gap: What Handspread Needs to Build

EdgarPack gives you audited financial data from SEC filings with full provenance. Finnhub gives you current market data. Handspread is the layer that combines them to produce a professional comp table.

### Layer 1: Market Data Client

A thin wrapper around Finnhub that fetches price and shares outstanding for a list of tickers.

**Input:** List of tickers
**Output:** For each ticker: `{ price, shares_outstanding, market_cap, as_of_timestamp }`

Design considerations:
- Market cap should be computed as `price * shares_outstanding`, not taken from Finnhub's pre-computed field (so the math is auditable)
- Rate limiting: 60 calls/min means ~30 tickers/min (2 calls each). For typical comp sets (5-15 companies) this is fine without throttling.
- Cache with short TTL (market data goes stale). Unlike SEC data which is immutable, prices change.

### Layer 2: Enterprise Value Bridge

This combines market data with balance sheet data from edgarpack. The full bridge:

```
Enterprise Value = Equity Value
                 + Total Debt (short_term_debt + total_debt)
                 + Preferred Stock (preferred_stock)
                 + Noncontrolling Interests (noncontrolling_interests)
                 - Cash (cash)
                 - Marketable Securities (marketable_securities)
                 +/- Operating Lease Liabilities (operating_lease_liabilities, if included)
                 -/+ Equity Method Investments (equity_method_investments, if excluded)
```

EdgarPack now provides all six balance sheet building blocks as cited metrics. Handspread computes the bridge, handling None values gracefully (if `preferred_stock` resolves to None for a company, treat it as zero).

Every component traces to its source:
- Price traces to Finnhub quote timestamp
- Shares outstanding traces to Finnhub profile (or edgarpack `shares_outstanding` from SEC filing)
- Each balance sheet item traces to a specific SEC filing (accession number, XBRL concept, filing URL)

See the Appendix for the full methodology, adjustments that matter, and the NVIDIA worked example.

### Layer 3: Valuation Multiples

With EV and market data, compute the standard multiple set:

**EV-based multiples:**
- EV / Revenue
- EV / EBITDA
- EV / EBIT (operating income)
- EV / Free Cash Flow

**Equity-based multiples:**
- P/E (Price / EPS diluted)
- Price / Book (Market Cap / Stockholders' Equity)

**Each multiple needs:**
- The numerator source (EV components or price)
- The denominator source (SEC filing with full citation)
- The period basis (LFY, LTM, NTM if you add forward estimates later)
- The computed value

### Layer 4: Operating Metrics

EdgarPack already computes many of these (margins, ratios), but handspread should also compute:

**Growth rates (requires annual:2 or quarterly series):**
- Revenue growth (YoY)
- EBITDA growth (YoY)
- Net income growth (YoY)
- EPS growth (YoY)

**Additional operating metrics:**
- R&D as % of revenue
- SG&A as % of revenue
- Capex as % of revenue
- Free cash flow yield (FCF / Market Cap)
- Dividend yield (Dividends Per Share / Price)

**Revenue per share** (Revenue / Shares Diluted) is useful for some analyses.

### Layer 5: Provenance Chain

This is what separates handspread from a quick script. Every computed value should carry:

1. **The value itself** (e.g., 15.2x)
2. **The formula** (e.g., "enterprise_value / ebitda")
3. **Each component's source** (e.g., EV from market cap + debt - cash; EBITDA from operating_income + D&A)
4. **Each component's provenance** (e.g., "revenue from NVIDIA CORP 10-K FY2025, filed 2025-02-18, accession 0001045810-25-000001")
5. **The SEC filing URL** for any SEC-sourced component
6. **The market data timestamp** for any market-sourced component

EdgarPack's CitedValue already carries items 4 and 5. Handspread needs to extend this pattern for market-sourced data and computed multiples.

---

## The Full Metric Set for a Professional Comp Table

This is what a complete handspread produces per company. Group them logically:

### Identification
- Company name
- Ticker
- CIK
- Fiscal year end

### Market Data (from Finnhub)
- Stock price
- Shares outstanding
- Market cap (computed: price * shares)

### Enterprise Value Bridge (computed, auditable)
- Market cap
- Plus: Total debt (from SEC filing)
- Less: Cash and equivalents (from SEC filing)
- Equals: Enterprise value

### Income Statement (from SEC filings, LFY or LTM)
- Revenue
- Cost of revenue
- Gross profit
- R&D expense
- SG&A expense
- Operating income (EBIT)
- EBITDA
- Net income
- EPS (diluted)

### Balance Sheet (from SEC filings, most recent)
- Total assets
- Cash
- Total debt
- Stockholders' equity
- Working capital

### Cash Flow (from SEC filings, LFY or LTM)
- Operating cash flow
- Capital expenditures
- Free cash flow

### Margins (computed from SEC data)
- Gross margin
- Operating margin
- EBITDA margin (EBITDA / Revenue)
- Net margin
- FCF margin (FCF / Revenue)

### Growth Rates (computed from multi-year SEC data)
- Revenue growth (YoY)
- EBITDA growth (YoY)
- Net income growth (YoY)
- EPS growth (YoY)

### Valuation Multiples (computed, combining market + SEC data)
- EV / Revenue
- EV / EBITDA
- EV / EBIT
- P/E (Price / EPS diluted)
- Price / Book
- EV / FCF
- FCF Yield

### Returns & Efficiency (computed from SEC data)
- ROE
- ROA
- ROIC (if computable: NOPAT / Invested Capital)

---

## Architecture Recommendation

```
handspread/
    __init__.py
    market/              # Finnhub client, market data models
        __init__.py
        finnhub.py       # Thin wrapper: fetch price + shares for ticker list
        models.py        # MarketData, MarketSnapshot dataclasses
    analysis/            # The computation engine
        __init__.py
        enterprise_value.py  # EV bridge computation
        multiples.py         # Valuation multiple computation
        growth.py            # YoY growth rate computation
        operating.py         # Additional operating metrics
    models.py            # Core data models: CompanyAnalysis, Provenance, etc.
    engine.py            # Orchestrator: wires edgarpack + market + analysis
    config.py            # Finnhub API key, cache settings
tests/
    ...
pyproject.toml
```

### Key Design Principles

**1. Import edgarpack, don't fork it.**
edgarpack is a clean library with a stable async API. Install it as `pip install -e ../edgarpack` and call `financials()` / `comps()` directly. No reason to duplicate concept resolution, period selection, or the citation chain.

**2. Extend the provenance pattern.**
EdgarPack's CitedValue carries full SEC provenance. Handspread should define a parallel `MarketValue` model for Finnhub-sourced data, and a `ComputedValue` model for anything handspread computes. Every number traces back to its source(s).

**3. Async throughout.**
EdgarPack is async. Finnhub calls are I/O bound. The orchestrator should fetch SEC data and market data concurrently for all companies.

**4. Fail gracefully per company.**
If one company's data is incomplete (missing D&A means no EBITDA means no EV/EBITDA), produce what you can and mark what's missing. Don't let one company's gaps tank the entire analysis.

**5. Period consistency.**
When computing multiples, the fiscal period of the denominator matters. EV/Revenue(LFY) and EV/Revenue(LTM) are different numbers. Be explicit about which period each metric uses, and keep it consistent across the comp set.

### The Orchestrator Pattern

```python
async def analyze_comps(
    tickers: list[str],
    period: str = "ltm",     # Default to LTM for multiples
) -> list[CompanyAnalysis]:
    """
    Full comparable company analysis.

    1. Fetch SEC financials for all companies (via edgarpack.comps)
    2. Fetch market data for all companies (via Finnhub)
    3. Compute enterprise value for each
    4. Compute valuation multiples for each
    5. Compute growth rates (requires annual:2 from edgarpack)
    6. Compute operating metrics
    7. Return fully-cited CompanyAnalysis objects
    """
```

The orchestrator should call edgarpack and Finnhub concurrently (they're independent I/O), then run computations sequentially (they depend on the fetched data).

### Dependencies

```toml
[project]
name = "handspread"
requires-python = ">=3.11"
dependencies = [
    "edgarpack",           # SEC financial data (installed editable from ../edgarpack)
    "finnhub-python",      # Market data
    "pydantic>=2.0",       # Data validation
]
```

### Environment Variables

- `FINNHUB_API_KEY` - Required. Free tier key from finnhub.io.
- `EDGARPACK_USER_AGENT` - Required by SEC. Format: `"Company admin@company.com"`

---

## What Success Looks Like

Given `analyze_comps(["NVDA", "AMD", "INTC", "AVGO", "QCOM"])`, the system should return a list of `CompanyAnalysis` objects where:

1. Every SEC-sourced number traces to a specific filing (accession, URL, date, XBRL concept)
2. Every market-sourced number traces to Finnhub with a timestamp
3. Every computed number (EV, multiples, growth rates) shows its formula and all component sources
4. Missing data produces `None` for that metric, not an error
5. The data is correct enough that an analyst could spot-check any number by clicking the SEC filing URL and finding the value in the document

The output at this stage is Python objects, not formatted output. A follow-up phase will handle rendering to Excel/HTML/PDF.

---

## Appendix: Banker-Grade Enterprise Value Construction

This section establishes the quality bar for enterprise value and valuation multiples. Every design decision in handspread should trace back to one governing principle.

### The Governing Principle

A comps table is implicitly asserting: the numerator and denominator of every multiple reflect the same underlying claim and the same economics, consistently across every company in the set.

EV represents the market value of operating assets, independent of capital structure. Revenue, EBITDA, EBIT, and FCF represent operating performance generated by those same assets over a defined period. Everything "nuanced" in professional comps work is just enforcing consistency when GAAP presentation, consolidation, capital structure, and one-time items break that alignment.

### Freeze the Valuation Date

All market data inputs must share a single as-of timestamp across the entire comp set:

- Share price (and FX rates if multi-currency)
- Share count and dilution assumptions
- Market cap and therefore EV numerator

Then use the latest reported balance sheet (most recent 10-Q or 10-K) for debt, cash, and other EV bridge items. If material events have occurred since quarter-end (new debt issuance, major buyback, acquisition close), note them as pro forma adjustments.

The most common junior mistake: EV date is "today" but net debt is "last quarter" without acknowledging the gap.

### Equity Value: Shares and Dilution

```
Equity Value = Price x Fully Diluted Shares Outstanding
```

For a comps spread, the standard approach:

1. Start with **basic shares outstanding** from the most recent filing
2. Add **incremental dilution** from in-the-money options/RSUs via Treasury Stock Method
3. The result is **fully diluted shares**

Consistency rule: use the same dilution methodology for every company in the set. A quick proxy (and what most first-pass comps use) is the delta between weighted-average basic and weighted-average diluted shares from the most recent quarter's EPS computation. EdgarPack provides both via `shares_outstanding` and `shares_diluted`.

**Convertibles:** avoid double-counting. If you include a convertible in debt, do not add if-converted shares. If you assume conversion into equity, add the shares and remove the convertible from debt. Pick one approach and apply it to every company.

### EV Bridge: The Full Anatomy

```
Enterprise Value = Equity Value
                 + Total Debt (short-term + long-term)
                 + Preferred Stock / Hybrid Claims
                 + Noncontrolling Interests
                 - Cash & Cash Equivalents
                 - Marketable Securities
                 +/- Other Adjustments (leases, pensions, investments)
```

Each item maps to an edgarpack metric:

| EV Bridge Item | EdgarPack Metric | Notes |
|----------------|-----------------|-------|
| Share price | *Finnhub* | `client.quote(symbol)["c"]` |
| Basic shares | `shares_outstanding` | Period-end from balance sheet |
| Diluted shares (proxy) | `shares_diluted` | Weighted-average from EPS computation |
| Long-term debt | `total_debt` | Maps to LongTermDebt XBRL concepts |
| Short-term debt | `short_term_debt` | Maps to DebtCurrent, ShortTermBorrowings |
| Cash | `cash` | CashAndCashEquivalentsAtCarryingValue |
| Marketable securities | `marketable_securities` | ShortTermInvestments, MarketableSecuritiesCurrent |
| Operating lease liabilities | `operating_lease_liabilities` | OperatingLeaseLiability (ASC 842) |
| Noncontrolling interests | `noncontrolling_interests` | MinorityInterest |
| Preferred stock | `preferred_stock` | PreferredStockValue |
| Equity method investments | `equity_method_investments` | For non-operating investment adjustment |

**Debt caveat:** XBRL reporting is inconsistent. Some companies include current portion in `LongTermDebt`; others separate it into `DebtCurrent`. When handspread sums `total_debt` + `short_term_debt`, it should sanity-check the total against the balance sheet. If both resolve to the same filing and the sum looks too high, one may already include the other.

### The Adjustments That Distinguish Professional Work

**Leases.** Post ASC 842/IFRS 16, operating lease liabilities appear on the balance sheet. Two acceptable approaches:

1. Exclude lease liabilities from EV (standard in tech comps, if peers are treated consistently)
2. Include lease liabilities as debt-like in EV

If you include leases in the numerator (EV), you should also normalize the denominator. Use EV/EBITDAR (add back rent/lease expense) so the lease financing treatment is consistent across peers. Mixing "leases in EV" with "leases in EBITDA" across IFRS and US GAAP reporters makes the multiple meaningless.

**Noncontrolling interests.** If a company consolidates a subsidiary it does not wholly own, the income statement includes 100% of that sub's revenue and EBITDA, but equity value reflects only the parent's claim. Add NCI to EV to keep numerator and denominator aligned. Missing this creates artificially low EV/EBITDA for companies with significant minority-owned subsidiaries.

**Non-operating investments.** If a company owns stakes in other entities that do not contribute to consolidated EBITDA, those investments inflate EV relative to operating earnings. For an "operating EV" you subtract equity method investments (and sometimes large non-marketable equity holdings). Flag this when it moves multiples, especially for companies with large strategic stakes.

**Cash: accessible vs trapped.** Not all cash is equally available to service debt or return to shareholders. Cash trapped by jurisdictional restrictions, regulatory capital requirements, or subsidiary-level constraints is not truly "net" against debt. For most comps, you subtract all reported cash. But when a company has material trapped cash, footnote it and show a sensitivity.

### NVIDIA Worked Example (as of Q3 FY26 Filing)

This example uses NVIDIA's 10-Q for the quarter ended October 26, 2025 (SEC accession: 000104581025000230) and an illustrative price of $182.81. In production, handspread would pull all of this programmatically.

**Equity Value**

| Component | Value | Source |
|-----------|-------|--------|
| Price per share | $182.81 | Finnhub quote |
| Basic shares outstanding | 24,305M | 10-Q balance sheet |
| Incremental dilution (proxy) | 156M | Diluted minus basic weighted-avg from Q3 EPS |
| **Fully diluted shares** | **24,461M** | |
| **Equity value** | **~$4,472B** | Price x FD shares |

**EV Bridge**

| Item | Amount ($M) | Source |
|------|-------------|--------|
| Equity value | 4,471,715 | Computed above |
| + Short-term debt | 999 | 10-Q: DebtCurrent |
| + Long-term debt | 7,468 | 10-Q: LongTermDebtNoncurrent |
| - Cash & equivalents | (11,486) | 10-Q: CashAndCashEquivalentsAtCarryingValue |
| - Marketable securities | (49,122) | 10-Q: ShortTermInvestments |
| **Enterprise value (base)** | **~$4,420B** | |

**Optional adjustments (show as sensitivity):**

| Adjustment | Amount ($M) | Notes |
|------------|-------------|-------|
| + Operating lease liabilities | 2,355 | Current ($341M) + noncurrent ($2,014M) |
| - Non-marketable equity investments | (8,187) | Strategic investments, not in EBITDA |
| **EV (lease-adjusted, ex-investments)** | **~$4,414B** | |

**LTM Denominators**

Built from the four most recent reported quarters:

| Metric | Q4 FY25 | Q1 FY26 | Q2 FY26 | Q3 FY26 | **LTM** |
|--------|---------|---------|---------|---------|---------|
| Revenue | 39,331 | 44,062 | 46,743 | 57,006 | **187,142** |
| Gross profit | 28,723 | 26,668 | 33,853 | 41,849 | **131,093** |
| Operating income | 24,034 | 21,638 | 28,440 | 36,010 | **110,122** |
| D&A (from cash flow) | 543 | 612 | 668 | 751 | **2,574** |
| **EBITDA (calc)** | | | | | **112,696** |
| Net income | 22,091 | 18,775 | 26,422 | 31,910 | **99,198** |
| Free cash flow | 15,519 | 26,136 | 13,450 | 22,089 | **77,194** |

Note: Q1 FY26 gross profit is lower because of a $4.5B charge related to H20 excess inventory. A professional spread would show both "reported LTM" and "normalized LTM" (excluding the charge) so the reader can judge for themselves.

**Resulting Multiples (LTM)**

| Multiple | Computation | Value |
|----------|------------|-------|
| EV / Revenue | 4,419,574 / 187,142 | **23.6x** |
| EV / EBITDA | 4,419,574 / 112,696 | **39.2x** |
| EV / EBIT | 4,419,574 / 110,122 | **40.1x** |
| EV / FCF | 4,419,574 / 77,194 | **57.3x** |
| P/E | 4,471,715 / 99,198 | **45.1x** |

Every number here traces to either a Finnhub timestamp or a specific SEC filing. That is the quality bar.

### Denominator Construction: Making Metrics Comparable

**LTM methodology.** EdgarPack's `ltm` period selector computes trailing twelve months using:

```
LTM = MRP_cumulative + LFY_annual - MRP_prior_year_cumulative
```

This gives the same result as summing the latest four standalone quarters. For the NVIDIA example: the Q3 FY26 nine-month cumulative ($147,811M revenue) + FY25 annual ($130,497M) - Q3 FY25 nine-month cumulative ($91,166M) = $187,142M LTM revenue.

**EBITDA definition.** NVIDIA (and most companies) does not report EBITDA as a GAAP line item. Build it as Operating Income + D&A, and label it "EBITDA (calc)" so there is no ambiguity. If the comp set uses company-adjusted EBITDA, apply the same adjustment categories to every peer.

**Stock-based compensation.** In software and semiconductor comps, SBC is material. Decide whether EBITDA is before or after SBC and enforce it uniformly. Mixing treatments across peers makes the multiple useless. The standard in tech comps is to show both "EBITDA" (including SBC as an expense) and sometimes "Adjusted EBITDA" (excluding SBC), with clear labels.

**IFRS vs US GAAP.** If the comp set mixes IFRS and GAAP reporters, IFRS 16 treats all leases like finance leases (depreciation + interest), while US GAAP ASC 842 keeps operating leases with straight-line expense. This can distort EBITDA comparisons. When it matters, use EV/EBITDAR to normalize.

**Growth rates.** Use `annual:2` from edgarpack to get the last two fiscal years, then compute YoY growth. For LTM-based growth, you need LTM for the current period and LTM for the same period one year ago.

### The Consistency Checklist

Handspread should run these checks on every comp set before presenting results:

**EV bridge checks:**
- Same as-of date for all share prices across the comp set
- Same dilution methodology (all use TSM proxy, or all use basic-only)
- No convertible double-counting (convert in debt XOR if-converted shares in equity, not both)
- NCI included in EV for companies that consolidate minority-owned subs
- Lease treatment applied uniformly (all exclude or all include, with denominator adjusted accordingly)
- Cash definition consistent (cash only, or cash + marketable securities, for all companies)

**Denominator checks:**
- Same period basis across all companies (all LTM, all LFY, or all NTM)
- EBITDA definition consistent (all GAAP operating income + D&A, or all company-adjusted with same categories)
- SBC treatment consistent
- One-time items either normalized for all peers or left in for all peers

**Sanity checks:**
- Debt total (short-term + long-term) should approximate what the company reports as total debt. If it diverges, check for XBRL overlap.
- Market cap should be within ~1% of what financial data providers show
- Multiples should be in a reasonable range for the sector. A 500x EV/EBITDA likely means a data error, not a premium.
