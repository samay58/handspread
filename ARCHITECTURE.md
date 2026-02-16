# How Handspread Works

Handspread builds comparable company analysis from primary data. It pulls financial statement values from SEC filings through edgarpack, pulls live market inputs from Finnhub, and computes analysis metrics on top. Provenance matters because you can trace every output number back to either a filing citation or a market API response.

## The Three Data Streams

For each ticker, Handspread fetches three inputs at the same time:

SEC EDGAR (LTM metrics)  -----\
SEC EDGAR (annual series) -----> Per-Company Analysis
Finnhub (market data)    -----/

In code, this happens with `asyncio.gather(...)` inside `analyze_comps()`. Each stream can fail without taking down the whole run. If one company fails a stream, the result object keeps partial data and records the error.

## What Gets Computed

NVIDIA is a good running example because it appears in the sample script.

### EV Bridge

Enterprise value starts from equity value (market cap), then adjusts for balance-sheet items.

Illustrative NVIDIA-style inputs:

- Price: `$182`
- Shares: `24.3B`
- Market cap: `$4,422.6B`
- Total debt: `$8.5B`
- Cash: `$11.5B`
- Marketable securities: `$49.1B`

Example:

- `EV = 4,422.6 + 8.5 - 11.5 - 49.1 = 4,370.5` (billions USD)

### Multiples

Multiples divide value by an operating or earnings measure.

- `EV / Revenue = 4,370.5 / 187.0 = 23.4x`
- `EV / EBITDA = 4,370.5 / 112.7 = 38.8x`
- `P/E = Market Cap / Net Income = 4,422.6 / 99.2 = 44.6x`
- `FCF Yield = FCF / Market Cap = 77.2 / 4,422.6 = 1.7%`

### Growth

Growth uses annual series values from SEC data.

- Revenue this year: `$130B`
- Revenue prior year: `$100B`
- `Revenue YoY = (130 - 100) / 100 = 30%`

The same pattern is used for EBITDA, net income, EPS diluted, and depreciation/amortization.

### Operating Metrics

Operating metrics show cost structure and capital efficiency.

- `R&D % of revenue = R&D / Revenue`
- `SG&A % of revenue = SG&A / Revenue`
- `Capex % of revenue = Capex / Revenue`
- `Revenue per share = Revenue / Shares`
- `ROIC = Operating Income * (1 - tax_rate) / (Debt + Equity)`

Example ROIC:

- Operating income: `$110B`
- Tax rate: `21%`
- Debt + equity: `$1,000B`
- `ROIC = 110 * 0.79 / 1,000 = 8.7%`

## The Provenance Chain

Handspread has three value types.

- `MarketValue`: raw Finnhub datapoint. Example: price from `quote` endpoint with fetch timestamp.
- `CitedValue`: raw SEC datapoint from edgarpack with filing metadata.
- `ComputedValue`: derived metric with a formula string and the source values used.

That means any output can be audited end to end.

Example trace for `EV/Revenue`:

- Numerator is `enterprise_value` (`ComputedValue`)
- EV references `market_cap` (`ComputedValue`) and debt/cash SEC inputs (`CitedValue`)
- Market cap references price and shares (`MarketValue`)
- Denominator is revenue (`CitedValue`)

## Enterprise Value Bridge

An EV bridge shows how you move from equity value to enterprise value. Analysts disagree on some adjustments, so Handspread makes those choices explicit through `EVPolicy`.

In plain terms, policy controls:

- Whether cash is subtracted
- Whether leases are included as debt-like items
- Whether debt uses total only, split debt, or total plus short-term debt
- Whether equity-method investments are subtracted

Formula assembly follows the selected policy and records each included component in the output object.

## How the Code is Organized

- `handspread/engine.py`: orchestrates async fetches and assembles company outputs.
- `handspread/market/finnhub_client.py`: fetches and caches Finnhub market inputs.
- `handspread/analysis/enterprise_value.py`: builds EV bridge objects.
- `handspread/analysis/multiples.py`: computes valuation multiples and yields.
- `handspread/analysis/growth.py`: computes YoY growth from annual series.
- `handspread/analysis/operating.py`: computes operating ratios and ROIC.
- `handspread/models.py`: data models for market, cited, and computed values.
- `handspread/config.py`: environment-backed runtime settings.
- `examples/run_comps.py`: runnable sample for a small ticker set.

## Running It

Quickstart:

```bash
uv pip install -e "../edgarpack"
uv pip install -e ".[dev]"

FINNHUB_API_KEY=<your-key> \
EDGARPACK_USER_AGENT="Name email@co.com" \
python examples/run_comps.py
```

Example output (shape):

```text
============================================================
NVIDIA CORP (NVDA) | CIK: 0001045810
============================================================
  Price:      $182.00
  Shares:     24,300,000,000
  Market Cap: $4,422,600,000,000
  EV:         $4,370,500,000,000

  Multiples:
    ev_revenue: 23.4x
    ev_ebitda: 38.8x
    pe: 44.6x
    fcf_yield: 1.7%
```
