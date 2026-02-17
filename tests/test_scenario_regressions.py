"""Scenario regression tests for production risk cohorts."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from edgarpack.query.models import QueryResult

from handspread.engine import analyze_comps
from handspread.models import ComputedValue, EVPolicy, MarketSnapshot, MarketValue


def _cited(value, metric: str, unit: str | None = "USD"):
    return SimpleNamespace(value=value, metric=metric, unit=unit)


def _snapshot(symbol: str, price: float, shares: float) -> MarketSnapshot:
    now = datetime(2026, 2, 17, 12, 0, tzinfo=UTC)
    price_mv = MarketValue(
        metric="price",
        value=price,
        unit="USD",
        vendor="finnhub",
        symbol=symbol,
        endpoint="quote",
        fetched_at=now,
    )
    shares_mv = MarketValue(
        metric="shares_outstanding",
        value=shares,
        unit="shares",
        vendor="finnhub",
        symbol=symbol,
        endpoint="profile",
        fetched_at=now,
    )
    market_cap = ComputedValue(
        metric="market_cap",
        value=price * shares,
        unit="USD",
        formula="price * shares_outstanding",
    )
    return MarketSnapshot(
        symbol=symbol,
        company_name=f"{symbol} Corp",
        price=price_mv,
        shares_outstanding=shares_mv,
        market_cap=market_cap,
    )


def _query_result(symbol: str, metrics: dict, period: str = "ltm") -> QueryResult:
    return QueryResult.model_construct(
        company=f"{symbol} Corp",
        cik=f"{abs(hash(symbol)) % (10**10):010d}",
        period=period,
        metrics=metrics,
    )


def _ltm_metrics(unit: str = "USD", **overrides):
    base = {
        "revenue": _cited(20_000_000_000, "revenue", unit),
        "gross_profit": _cited(14_000_000_000, "gross_profit", unit),
        "ebitda": _cited(6_000_000_000, "ebitda", unit),
        "operating_income": _cited(5_000_000_000, "operating_income", unit),
        "depreciation_amortization": _cited(1_000_000_000, "depreciation_amortization", unit),
        "stock_based_compensation": _cited(500_000_000, "stock_based_compensation", unit),
        "free_cash_flow": _cited(4_000_000_000, "free_cash_flow", unit),
        "net_income": _cited(3_000_000_000, "net_income", unit),
        "stockholders_equity": _cited(15_000_000_000, "stockholders_equity", unit),
        "total_debt": _cited(8_000_000_000, "total_debt", unit),
        "cash": _cited(2_000_000_000, "cash", unit),
        "marketable_securities": _cited(1_000_000_000, "marketable_securities", unit),
        "equity_method_investments": _cited(500_000_000, "equity_method_investments", unit),
        "operating_lease_liabilities": _cited(3_000_000_000, "operating_lease_liabilities", unit),
        "rd_expense": _cited(2_000_000_000, "rd_expense", unit),
        "sga_expense": _cited(4_000_000_000, "sga_expense", unit),
        "capex": _cited(1_500_000_000, "capex", unit),
        "dividends_per_share": _cited(2.0, "dividends_per_share", f"{unit}/shares"),
    }
    for key, value in overrides.items():
        if value is None:
            base.pop(key, None)
        else:
            base[key] = value
    return base


def _growth_metrics(unit: str = "USD"):
    """LTM-1 values: single CitedValue per metric (prior year trailing twelve months)."""
    return {
        "revenue": _cited(18_000_000_000, "revenue", unit),
        "ebitda": _cited(5_000_000_000, "ebitda", unit),
        "net_income": _cited(2_500_000_000, "net_income", unit),
        "eps_diluted": _cited(2.0, "eps_diluted", unit),
        "depreciation_amortization": _cited(900_000_000, "depreciation_amortization", unit),
        "gross_profit": _cited(12_000_000_000, "gross_profit", unit),
        "operating_income": _cited(4_500_000_000, "operating_income", unit),
        "stock_based_compensation": _cited(400_000_000, "stock_based_compensation", unit),
    }


async def _run_analysis(
    tickers: list[str],
    ltm_data: dict[str, QueryResult],
    growth_data: dict[str, QueryResult],
    market_data: dict[str, MarketSnapshot],
    ev_policy: EVPolicy | None = None,
):
    async def _mock_comps(requested_tickers, _requested_metrics, period):
        assert requested_tickers == tickers
        return growth_data if period == "ltm-1" else ltm_data

    with (
        patch("handspread.engine.comps", new=AsyncMock(side_effect=_mock_comps)),
        patch("handspread.engine.fetch_market_snapshots", new=AsyncMock(return_value=market_data)),
    ):
        return await analyze_comps(tickers, ev_policy=ev_policy)


@pytest.mark.asyncio
async def test_big_tech_baseline_golden_path():
    tickers = ["AAPL", "MSFT", "GOOG", "AMZN", "META", "NVDA"]
    ltm = {}
    growth = {}
    market = {}

    for ticker in tickers:
        overrides = {}
        if ticker == "AAPL":
            overrides["stockholders_equity"] = _cited(-2_000_000_000, "stockholders_equity", "USD")
        ltm[ticker] = _query_result(ticker, _ltm_metrics(**overrides))
        growth[ticker] = _query_result(ticker, _growth_metrics(), period="ltm-1")
        market[ticker] = _snapshot(ticker, price=100.0, shares=1_000_000_000)

    results = await _run_analysis(tickers, ltm, growth, market)

    assert len(results) == len(tickers)
    for result in results:
        assert result.ev_bridge is not None
        assert result.ev_bridge.enterprise_value is not None
        assert result.ev_bridge.enterprise_value.value is not None
        assert "revenue_yoy" in result.growth
        assert "net_income_yoy" in result.growth
        assert "gross_margin_chg" in result.growth
        assert "ebitda_margin_chg" in result.growth
        assert "adjusted_ebitda_margin_chg" in result.growth
        assert "rd_pct_revenue" in result.operating
        assert "sga_pct_revenue" in result.operating
        assert "gross_margin" in result.operating
        assert "ebitda_margin" in result.operating
        assert "adjusted_ebitda_margin" in result.operating

    aapl = next(r for r in results if r.symbol == "AAPL")
    assert aapl.multiples["price_book"].value is not None
    assert aapl.multiples["price_book"].value < 0
    assert any("Negative denominator" in w for w in aapl.multiples["price_book"].warnings)


@pytest.mark.asyncio
async def test_financials_show_expected_metric_gaps():
    tickers = ["JPM", "GS", "BAC", "WFC", "MS"]
    ltm = {}
    growth = {}
    market = {}

    for ticker in tickers:
        ltm[ticker] = _query_result(
            ticker,
            _ltm_metrics(
                ebitda=None,
                operating_income=None,
                free_cash_flow=None,
                rd_expense=None,
                sga_expense=None,
                capex=None,
                dividends_per_share=None,
            ),
        )
        growth[ticker] = _query_result(ticker, _growth_metrics(), period="ltm-1")
        market[ticker] = _snapshot(ticker, price=80.0, shares=2_000_000_000)

    results = await _run_analysis(tickers, ltm, growth, market)

    for result in results:
        assert result.multiples["ev_revenue"].value is not None
        assert result.multiples["pe"].value is not None
        assert result.multiples["ev_ebitda"].value is None
        assert result.multiples["ev_ebit"].value is None
        assert result.multiples["ev_fcf"].value is None
        assert "ebitda_margin" not in result.operating
        assert "adjusted_ebitda_margin" not in result.operating


@pytest.mark.asyncio
async def test_negative_equity_buyback_names():
    tickers = ["SBUX", "MCD", "BA", "HLT"]
    ltm = {}
    growth = {}
    market = {}

    for ticker in tickers:
        overrides = {
            "stockholders_equity": _cited(-2_000_000_000, "stockholders_equity", "USD"),
            "total_debt": _cited(5_000_000_000, "total_debt", "USD"),
        }
        if ticker == "HLT":
            overrides["total_debt"] = _cited(500_000_000, "total_debt", "USD")
            overrides["stockholders_equity"] = _cited(-1_000_000_000, "stockholders_equity", "USD")

        ltm[ticker] = _query_result(ticker, _ltm_metrics(**overrides))
        growth[ticker] = _query_result(ticker, _growth_metrics(), period="ltm-1")
        market[ticker] = _snapshot(ticker, price=120.0, shares=300_000_000)

    results = await _run_analysis(tickers, ltm, growth, market)

    for result in results:
        assert result.errors == []
        assert any("Negative denominator" in w for w in result.multiples["price_book"].warnings)

    hlt = next(r for r in results if r.symbol == "HLT")
    assert "roic" not in hlt.operating


@pytest.mark.asyncio
async def test_reits_exercise_lease_inclusion_path():
    tickers = ["AMT", "PLD", "SPG", "O", "EQIX"]
    ltm = {}
    growth = {}
    market = {}

    for ticker in tickers:
        ltm[ticker] = _query_result(
            ticker,
            _ltm_metrics(
                operating_lease_liabilities=_cited(
                    12_000_000_000, "operating_lease_liabilities", "USD"
                ),
            ),
        )
        growth[ticker] = _query_result(ticker, _growth_metrics(), period="ltm-1")
        market[ticker] = _snapshot(ticker, price=90.0, shares=500_000_000)

    results = await _run_analysis(
        tickers,
        ltm,
        growth,
        market,
        ev_policy=EVPolicy(include_leases=True),
    )

    for result in results:
        assert result.ev_bridge is not None
        assert result.ev_bridge.operating_lease_liabilities is not None
        assert "operating_lease_liabilities" in result.ev_bridge.enterprise_value.formula
        assert result.multiples["ev_ebitda"].value is not None


@pytest.mark.asyncio
async def test_pre_revenue_and_deep_loss_names():
    tickers = ["RIVN", "LCID", "IONQ", "DNA"]
    ltm = {}
    growth = {}
    market = {}

    for ticker in tickers:
        ltm[ticker] = _query_result(
            ticker,
            _ltm_metrics(
                revenue=_cited(25_000_000, "revenue", "USD"),
                net_income=_cited(-3_000_000_000, "net_income", "USD"),
                free_cash_flow=_cited(-2_000_000_000, "free_cash_flow", "USD"),
                stockholders_equity=_cited(8_000_000_000, "stockholders_equity", "USD"),
            ),
        )
        growth[ticker] = _query_result(ticker, _growth_metrics(), period="ltm-1")
        market[ticker] = _snapshot(ticker, price=60.0, shares=1_000_000_000)

    results = await _run_analysis(tickers, ltm, growth, market)

    for result in results:
        assert result.errors == []
        assert result.multiples["ev_revenue"].value is not None
        assert result.multiples["ev_revenue"].value > 100
        assert result.multiples["pe"].value is not None
        assert result.multiples["pe"].value < 0
        assert any("Negative denominator" in w for w in result.multiples["pe"].warnings)


@pytest.mark.asyncio
async def test_conglomerates_with_equity_method_adjustment():
    tickers = ["BRK.B", "MMM", "JNJ", "RTX"]
    ltm = {}
    growth = {}
    market = {}

    for ticker in tickers:
        overrides = {}
        if ticker == "BRK.B":
            overrides = {
                "total_debt": _cited(100_000_000_000, "total_debt", "USD"),
                "cash": _cited(30_000_000_000, "cash", "USD"),
                "marketable_securities": _cited(200_000_000_000, "marketable_securities", "USD"),
                "equity_method_investments": _cited(
                    50_000_000_000, "equity_method_investments", "USD"
                ),
            }

        ltm[ticker] = _query_result(ticker, _ltm_metrics(**overrides))
        growth[ticker] = _query_result(ticker, _growth_metrics(), period="ltm-1")
        market[ticker] = _snapshot(ticker, price=500.0, shares=2_000_000_000)

    results = await _run_analysis(
        tickers,
        ltm,
        growth,
        market,
        ev_policy=EVPolicy(subtract_equity_method_investments=True),
    )

    brkb = next(r for r in results if r.symbol == "BRK.B")
    assert brkb.ev_bridge is not None
    assert brkb.ev_bridge.equity_method_investments is not None
    assert brkb.ev_bridge.marketable_securities is not None

    expected_ev = (
        500.0 * 2_000_000_000 + 100_000_000_000 - 30_000_000_000 - 200_000_000_000 - 50_000_000_000
    )
    assert brkb.ev_bridge.enterprise_value.value == expected_ev


@pytest.mark.asyncio
async def test_foreign_adr_currency_mismatch_behavior():
    tickers = ["TSM", "ASML", "SAP", "TM", "NVO", "SONY"]
    unit_map = {"TSM": "TWD", "ASML": "EUR", "SAP": "EUR", "TM": "JPY", "NVO": "DKK", "SONY": "JPY"}
    ltm = {}
    growth = {}
    market = {}

    for ticker in tickers:
        currency = unit_map[ticker]
        ltm[ticker] = _query_result(ticker, _ltm_metrics(unit=currency))
        growth[ticker] = _query_result(ticker, _growth_metrics(unit=currency), period="ltm-1")
        market[ticker] = _snapshot(ticker, price=100.0, shares=1_000_000_000)

    results = await _run_analysis(tickers, ltm, growth, market)

    for result in results:
        assert result.ev_bridge is not None
        assert result.ev_bridge.enterprise_value.value is None
        assert any("cannot mix currencies" in w for w in result.ev_bridge.enterprise_value.warnings)
        assert result.multiples["pe"].value is None
        assert any("cannot mix currencies" in w for w in result.multiples["pe"].warnings)
        assert result.operating["rd_pct_revenue"].value is not None
        assert result.operating["revenue_per_share"].unit != "USD/shares"
        assert any(
            "cannot mix currencies" in w for w in result.operating["revenue_per_share"].warnings
        )


@pytest.mark.asyncio
async def test_chinese_adr_cluster_cny_behavior():
    tickers = ["BABA", "PDD", "JD", "BIDU", "NIO"]
    unit_map = {"BABA": "CNY", "PDD": "CNY", "JD": "CNY", "BIDU": "USD", "NIO": "CNY"}
    ltm = {}
    growth = {}
    market = {}

    for ticker in tickers:
        currency = unit_map[ticker]
        ltm[ticker] = _query_result(ticker, _ltm_metrics(unit=currency))
        growth[ticker] = _query_result(ticker, _growth_metrics(unit=currency), period="ltm-1")
        market[ticker] = _snapshot(ticker, price=70.0, shares=1_200_000_000)

    results = await _run_analysis(tickers, ltm, growth, market)

    for result in results:
        if result.symbol == "BIDU":
            assert result.ev_bridge.enterprise_value.value is not None
            assert result.multiples["pe"].value is not None
        else:
            assert result.ev_bridge.enterprise_value.value is None
            assert result.multiples["pe"].value is None
            assert any("cannot mix currencies" in w for w in result.multiples["pe"].warnings)


@pytest.mark.asyncio
async def test_adr_market_cap_uses_vendor():
    """ADR ticker should use vendor-reported market cap, not inflated price * shares."""
    tickers = ["TSM"]
    ltm = {"TSM": _query_result("TSM", _ltm_metrics(unit="TWD"))}
    growth = {"TSM": _query_result("TSM", _growth_metrics(unit="TWD"), period="ltm-1")}

    # Simulate ADR: ordinary shares are 25.9B but the ADR price is $200
    # Vendor market cap is $950B (correct), computed would be $5.18T (wrong)
    now = datetime(2026, 2, 17, 12, 0, tzinfo=UTC)
    price_mv = MarketValue(
        metric="price",
        value=200.0,
        unit="USD",
        vendor="finnhub",
        symbol="TSM",
        endpoint="quote",
        fetched_at=now,
    )
    shares_mv = MarketValue(
        metric="shares_outstanding",
        value=25_900_000_000,
        unit="shares",
        vendor="finnhub",
        symbol="TSM",
        endpoint="profile",
        fetched_at=now,
    )
    # Vendor-reported market cap (not computed)
    mcap_mv = MarketValue(
        metric="market_cap",
        value=950_000_000_000,
        unit="USD",
        vendor="finnhub",
        symbol="TSM",
        endpoint="profile",
        fetched_at=now,
        notes=["Vendor-reported marketCapitalization=950000M from profile endpoint"],
    )
    market = {
        "TSM": MarketSnapshot(
            symbol="TSM",
            company_name="TSM Corp",
            price=price_mv,
            shares_outstanding=shares_mv,
            market_cap=mcap_mv,
        )
    }
    results = await _run_analysis(tickers, ltm, growth, market)
    tsm = results[0]
    # Market cap should be $950B, not $5.18T
    assert tsm.market.market_cap.value == 950_000_000_000


@pytest.mark.asyncio
async def test_captive_finance_debt():
    """Ford-like company should resolve consolidated debt from broad XBRL tags."""
    tickers = ["F"]
    ltm = {
        "F": _query_result(
            "F",
            _ltm_metrics(
                total_debt=_cited(160_000_000_000, "total_debt", "USD"),
            ),
        )
    }
    growth = {"F": _query_result("F", _growth_metrics(), period="ltm-1")}
    market = {"F": _snapshot("F", price=12.0, shares=4_000_000_000)}

    results = await _run_analysis(tickers, ltm, growth, market)
    f_result = results[0]
    assert f_result.ev_bridge is not None
    assert f_result.ev_bridge.enterprise_value.value is not None
    # EV should reflect the large debt position
    ev = f_result.ev_bridge.enterprise_value.value
    assert ev > 100_000_000_000  # EV > $100B given $160B debt


@pytest.mark.asyncio
async def test_annual_only_filer_growth():
    """20-F filer with annual-only data should show non-zero YoY growth."""
    tickers = ["TSM"]
    # LTM for annual-only filer resolves to most recent FY
    ltm = {
        "TSM": _query_result(
            "TSM",
            _ltm_metrics(
                revenue=_cited(90_000_000_000, "revenue", "USD"),
            ),
        )
    }
    # LTM-1 for annual-only filer resolves to prior FY
    growth = {
        "TSM": _query_result(
            "TSM",
            {
                "revenue": _cited(70_000_000_000, "revenue", "USD"),
                "ebitda": _cited(5_000_000_000, "ebitda", "USD"),
                "net_income": _cited(2_500_000_000, "net_income", "USD"),
                "eps_diluted": _cited(2.0, "eps_diluted", "USD"),
                "depreciation_amortization": _cited(
                    900_000_000, "depreciation_amortization", "USD"
                ),
                "gross_profit": _cited(12_000_000_000, "gross_profit", "USD"),
                "operating_income": _cited(4_500_000_000, "operating_income", "USD"),
                "stock_based_compensation": _cited(400_000_000, "stock_based_compensation", "USD"),
            },
            period="ltm-1",
        ),
    }
    market = {"TSM": _snapshot("TSM", price=200.0, shares=5_000_000_000)}

    results = await _run_analysis(tickers, ltm, growth, market)
    tsm = results[0]
    assert "revenue_yoy" in tsm.growth
    # Revenue grew from $70B to $90B = ~28.6% growth
    assert tsm.growth["revenue_yoy"].value is not None
    assert abs(tsm.growth["revenue_yoy"].value - (90 - 70) / 70) < 0.01
