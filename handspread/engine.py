"""Orchestrator: concurrent SEC + market data fetches into CompanyAnalysis objects."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from edgarpack.query import comps
from edgarpack.query.models import QueryResult

from .analysis.enterprise_value import build_ev_bridge
from .analysis.growth import compute_growth
from .analysis.multiples import compute_multiples
from .analysis.operating import compute_operating
from .market.finnhub_client import fetch_market_snapshots
from .models import CompanyAnalysis, EVPolicy, MarketSnapshot

# Metrics needed for EV bridge + multiples + operating
REQUIRED_METRICS = [
    "revenue",
    "cost_of_revenue",
    "gross_profit",
    "operating_income",
    "net_income",
    "ebitda",
    "depreciation_amortization",
    "eps_diluted",
    "rd_expense",
    "sga_expense",
    "total_assets",
    "total_liabilities",
    "stockholders_equity",
    "cash",
    "total_debt",
    "short_term_debt",
    "marketable_securities",
    "operating_lease_liabilities",
    "preferred_stock",
    "noncontrolling_interests",
    "equity_method_investments",
    "operating_cash_flow",
    "capex",
    "free_cash_flow",
    "shares_outstanding",
    "dividends_per_share",
]

# Metrics needed for growth (annual series)
GROWTH_METRICS = [
    "revenue",
    "ebitda",
    "net_income",
    "eps_diluted",
]


async def analyze_comps(
    tickers: list[str],
    period: str = "ltm",
    ev_policy: EVPolicy | None = None,
    timeout: float = 60.0,
) -> list[CompanyAnalysis]:
    """Run full comparable company analysis across tickers.

    Three concurrent data streams:
    1. SEC LTM/LFY financials (edgarpack.comps)
    2. SEC annual series for growth (edgarpack.comps with annual:2)
    3. Finnhub market data (price, shares outstanding)

    Returns one CompanyAnalysis per ticker. Failures are isolated per-company
    and recorded in the errors list rather than raising.
    """
    valuation_ts = datetime.now(UTC)

    sec_task = comps(tickers, REQUIRED_METRICS, period)
    growth_task = comps(tickers, GROWTH_METRICS, "annual:2")
    market_task = fetch_market_snapshots(tickers)

    try:
        sec_results, growth_results, market_results = await asyncio.wait_for(
            asyncio.gather(sec_task, growth_task, market_task, return_exceptions=True),
            timeout=timeout,
        )
    except TimeoutError:
        sec_results, growth_results, market_results = {}, {}, {}

    # Handle top-level failures
    if isinstance(sec_results, BaseException):
        sec_results = {}
    if isinstance(growth_results, BaseException):
        growth_results = {}
    if isinstance(market_results, BaseException):
        market_results = {}

    analyses: list[CompanyAnalysis] = []

    for ticker in tickers:
        analysis = _build_single(
            ticker=ticker,
            sec_result=sec_results.get(ticker),
            growth_result=growth_results.get(ticker),
            market_snapshot=market_results.get(ticker),
            period=period,
            ev_policy=ev_policy,
            valuation_ts=valuation_ts,
        )
        analyses.append(analysis)

    return analyses


def _build_single(
    ticker: str,
    sec_result: QueryResult | None,
    growth_result: QueryResult | None,
    market_snapshot: MarketSnapshot | None,
    period: str,
    ev_policy: EVPolicy | None,
    valuation_ts: datetime,
) -> CompanyAnalysis:
    """Assemble a CompanyAnalysis for one ticker. Never raises."""
    errors: list[str] = []
    warnings: list[str] = []

    company_name = ticker
    cik = ""

    if sec_result is not None:
        company_name = sec_result.company
        cik = sec_result.cik

    if market_snapshot is not None and company_name == ticker:
        company_name = market_snapshot.company_name

    if sec_result is None:
        errors.append("SEC data fetch failed")
    if market_snapshot is None:
        errors.append("Market data fetch failed")

    # SEC metrics as a flat dict
    sec_metrics = sec_result.metrics if sec_result else {}

    # EV bridge
    ev_bridge = None
    if market_snapshot is not None:
        try:
            ev_bridge = build_ev_bridge(market_snapshot, sec_metrics, ev_policy)
        except Exception as e:
            errors.append(f"EV bridge computation failed: {e}")

    # Multiples
    multiples = {}
    if ev_bridge is not None and market_snapshot is not None:
        try:
            multiples = compute_multiples(ev_bridge, market_snapshot, sec_metrics)
        except Exception as e:
            errors.append(f"Multiples computation failed: {e}")

    # Growth
    growth = {}
    if growth_result is not None:
        try:
            growth = compute_growth(growth_result.metrics)
        except Exception as e:
            errors.append(f"Growth computation failed: {e}")

    # Operating metrics
    operating = {}
    try:
        operating = compute_operating(sec_metrics, market_snapshot)
    except Exception as e:
        errors.append(f"Operating metrics computation failed: {e}")

    return CompanyAnalysis(
        symbol=ticker,
        company_name=company_name,
        cik=cik,
        period=period,
        valuation_timestamp=valuation_ts,
        market=market_snapshot,
        sec=sec_result,
        ev_bridge=ev_bridge,
        multiples=multiples,
        growth=growth,
        operating=operating,
        warnings=warnings,
        errors=errors,
    )
