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
        "cost_of_revenue": _cited(6_000_000_000, "cost_of_revenue", unit),
        "gross_profit": _cited(14_000_000_000, "gross_profit", unit),
        "ebitda": _cited(6_000_000_000, "ebitda", unit),
        "operating_income": _cited(5_000_000_000, "operating_income", unit),
        "depreciation_amortization": _cited(1_000_000_000, "depreciation_amortization", unit),
        "stock_based_compensation": _cited(500_000_000, "stock_based_compensation", unit),
        "operating_cash_flow": _cited(5_500_000_000, "operating_cash_flow", unit),
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
        "cost_of_revenue": _cited(6_000_000_000, "cost_of_revenue", unit),
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


@pytest.mark.asyncio
async def test_bank_missing_gross_profit_tag():
    """Bank/financial where GrossProfit XBRL tag is missing but revenue and COGS are present."""
    tickers = ["JPM"]
    ltm = {
        "JPM": _query_result(
            "JPM",
            _ltm_metrics(
                gross_profit=None,  # GrossProfit tag omitted by filer
                cost_of_revenue=_cited(6_000_000_000, "cost_of_revenue", "USD"),
            ),
        )
    }
    growth = {"JPM": _query_result("JPM", _growth_metrics(), period="ltm-1")}
    market = {"JPM": _snapshot("JPM", price=180.0, shares=2_800_000_000)}

    results = await _run_analysis(tickers, ltm, growth, market)
    jpm = results[0]

    # gross_margin should still compute from revenue - cost_of_revenue
    assert "gross_margin" in jpm.operating
    expected_gm = (20_000_000_000 - 6_000_000_000) / 20_000_000_000
    assert abs(jpm.operating["gross_margin"].value - expected_gm) < 0.001

    # Provenance should trace to components, not reported gross_profit
    gp_cv = jpm.operating["gross_margin"].components["gross_profit"]
    assert gp_cv.formula == "revenue - cost_of_revenue"


# ---------------------------------------------------------------------------
# Expanded Round 2 Scenario Cohorts (20-company basket)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_insurance_conglomerate_brk():
    """BRK.B: massive float-as-liability, equity portfolio, no standard EBITDA."""
    tickers = ["BRK.B"]
    ltm = {
        "BRK.B": _query_result(
            "BRK.B",
            _ltm_metrics(
                revenue=_cited(365_000_000_000, "revenue", "USD"),
                net_income=_cited(90_000_000_000, "net_income", "USD"),
                ebitda=None,  # BRK doesn't report meaningful GAAP EBITDA
                operating_income=None,
                depreciation_amortization=None,
                total_debt=_cited(120_000_000_000, "total_debt", "USD"),
                cash=_cited(40_000_000_000, "cash", "USD"),
                marketable_securities=_cited(300_000_000_000, "marketable_securities", "USD"),
                stockholders_equity=_cited(550_000_000_000, "stockholders_equity", "USD"),
                equity_method_investments=_cited(
                    50_000_000_000, "equity_method_investments", "USD"
                ),
            ),
        )
    }
    growth = {"BRK.B": _query_result("BRK.B", _growth_metrics(), period="ltm-1")}
    market = {"BRK.B": _snapshot("BRK.B", price=500.0, shares=2_160_000_000)}

    results = await _run_analysis(
        tickers,
        ltm,
        growth,
        market,
        ev_policy=EVPolicy(subtract_equity_method_investments=True),
    )
    brk = results[0]
    assert brk.errors == []
    assert brk.ev_bridge.enterprise_value.value is not None
    # EBITDA multiples should be None since EBITDA is missing
    assert brk.multiples["ev_ebitda"].value is None
    assert brk.multiples["pe"].value is not None


@pytest.mark.asyncio
async def test_reit_depreciation_heavy():
    """PLD: REIT where depreciation distorts earnings. FFO is the real metric."""
    tickers = ["PLD"]
    ltm = {
        "PLD": _query_result(
            "PLD",
            _ltm_metrics(
                revenue=_cited(8_000_000_000, "revenue", "USD"),
                net_income=_cited(2_000_000_000, "net_income", "USD"),
                depreciation_amortization=_cited(3_500_000_000, "depreciation_amortization", "USD"),
                operating_income=_cited(3_000_000_000, "operating_income", "USD"),
                total_debt=_cited(30_000_000_000, "total_debt", "USD"),
                stockholders_equity=_cited(35_000_000_000, "stockholders_equity", "USD"),
                operating_lease_liabilities=_cited(
                    500_000_000, "operating_lease_liabilities", "USD"
                ),
            ),
        )
    }
    growth = {"PLD": _query_result("PLD", _growth_metrics(), period="ltm-1")}
    market = {"PLD": _snapshot("PLD", price=120.0, shares=930_000_000)}

    results = await _run_analysis(tickers, ltm, growth, market)
    pld = results[0]
    assert pld.errors == []
    assert pld.ev_bridge.enterprise_value.value is not None
    # D&A is larger than net income; PE misleadingly high
    assert pld.multiples["pe"].value is not None
    assert pld.multiples["ev_ebitda"].value is not None


@pytest.mark.asyncio
async def test_mlp_partnership():
    """EPD: MLP with K-1 reporting, distributable cash flow."""
    tickers = ["EPD"]
    ltm = {
        "EPD": _query_result(
            "EPD",
            _ltm_metrics(
                revenue=_cited(50_000_000_000, "revenue", "USD"),
                net_income=_cited(5_500_000_000, "net_income", "USD"),
                operating_income=_cited(7_000_000_000, "operating_income", "USD"),
                depreciation_amortization=_cited(2_000_000_000, "depreciation_amortization", "USD"),
                total_debt=_cited(28_000_000_000, "total_debt", "USD"),
                cash=_cited(200_000_000, "cash", "USD"),
                stockholders_equity=_cited(30_000_000_000, "stockholders_equity", "USD"),
                dividends_per_share=_cited(2.10, "dividends_per_share", "USD/shares"),
            ),
        )
    }
    growth = {"EPD": _query_result("EPD", _growth_metrics(), period="ltm-1")}
    market = {"EPD": _snapshot("EPD", price=30.0, shares=2_170_000_000)}

    results = await _run_analysis(tickers, ltm, growth, market)
    epd = results[0]
    assert epd.errors == []
    assert epd.ev_bridge.enterprise_value.value is not None
    assert epd.multiples["ev_ebitda"].value is not None
    assert epd.multiples["dividend_yield"].value is not None


@pytest.mark.asyncio
async def test_bdc_nav_based():
    """ARCC: BDC where unrealized gains dominate earnings."""
    tickers = ["ARCC"]
    ltm = {
        "ARCC": _query_result(
            "ARCC",
            _ltm_metrics(
                revenue=_cited(3_000_000_000, "revenue", "USD"),
                net_income=_cited(2_500_000_000, "net_income", "USD"),  # Includes unrealized gains
                ebitda=None,
                operating_income=None,
                depreciation_amortization=None,
                total_debt=_cited(12_000_000_000, "total_debt", "USD"),
                cash=_cited(500_000_000, "cash", "USD"),
                stockholders_equity=_cited(12_500_000_000, "stockholders_equity", "USD"),
            ),
        )
    }
    growth = {"ARCC": _query_result("ARCC", _growth_metrics(), period="ltm-1")}
    market = {"ARCC": _snapshot("ARCC", price=22.0, shares=620_000_000)}

    results = await _run_analysis(tickers, ltm, growth, market)
    arcc = results[0]
    assert arcc.errors == []
    assert arcc.multiples["pe"].value is not None
    assert arcc.multiples["price_book"].value is not None
    # EBITDA multiple should be None (missing data)
    assert arcc.multiples["ev_ebitda"].value is None


@pytest.mark.asyncio
async def test_dual_class_share_structure():
    """GOOGL: three share classes complicate diluted share count."""
    tickers = ["GOOGL"]
    ltm = {
        "GOOGL": _query_result(
            "GOOGL",
            _ltm_metrics(
                revenue=_cited(340_000_000_000, "revenue", "USD"),
                net_income=_cited(85_000_000_000, "net_income", "USD"),
                eps_diluted=_cited(6.80, "eps_diluted", "USD/shares"),
                operating_income=_cited(100_000_000_000, "operating_income", "USD"),
                depreciation_amortization=_cited(
                    15_000_000_000, "depreciation_amortization", "USD"
                ),
                total_debt=_cited(30_000_000_000, "total_debt", "USD"),
                cash=_cited(25_000_000_000, "cash", "USD"),
                marketable_securities=_cited(80_000_000_000, "marketable_securities", "USD"),
                stockholders_equity=_cited(290_000_000_000, "stockholders_equity", "USD"),
            ),
        )
    }
    growth = {"GOOGL": _query_result("GOOGL", _growth_metrics(), period="ltm-1")}
    market = {"GOOGL": _snapshot("GOOGL", price=185.0, shares=12_300_000_000)}

    results = await _run_analysis(tickers, ltm, growth, market)
    googl = results[0]
    assert googl.errors == []
    assert googl.multiples["pe"].value is not None
    assert googl.multiples["ev_revenue"].value is not None
    assert googl.multiples["ev_ebitda"].value is not None


@pytest.mark.asyncio
async def test_recent_spinoff_limited_history():
    """GEV: < 2 years independent history, carve-out accounting."""
    tickers = ["GEV"]
    ltm = {
        "GEV": _query_result(
            "GEV",
            _ltm_metrics(
                revenue=_cited(35_000_000_000, "revenue", "USD"),
                net_income=_cited(4_000_000_000, "net_income", "USD"),
                operating_income=_cited(5_000_000_000, "operating_income", "USD"),
                depreciation_amortization=_cited(1_200_000_000, "depreciation_amortization", "USD"),
                total_debt=_cited(8_000_000_000, "total_debt", "USD"),
                cash=_cited(5_000_000_000, "cash", "USD"),
                stockholders_equity=_cited(15_000_000_000, "stockholders_equity", "USD"),
            ),
        )
    }
    # LTM-1 missing for spin-off (no comparable prior period)
    growth = {
        "GEV": _query_result(
            "GEV",
            {
                "revenue": _cited(None, "revenue", "USD"),
                "ebitda": _cited(None, "ebitda", "USD"),
                "net_income": _cited(None, "net_income", "USD"),
                "eps_diluted": _cited(None, "eps_diluted", "USD"),
                "depreciation_amortization": _cited(None, "depreciation_amortization", "USD"),
            },
            period="ltm-1",
        ),
    }
    market = {"GEV": _snapshot("GEV", price=400.0, shares=275_000_000)}

    results = await _run_analysis(tickers, ltm, growth, market)
    gev = results[0]
    assert gev.errors == []
    assert gev.ev_bridge.enterprise_value.value is not None
    # Growth should be absent due to no prior year data
    assert "revenue_yoy" not in gev.growth or gev.growth.get("revenue_yoy") is None


@pytest.mark.asyncio
async def test_shipping_cyclical_ebitda():
    """ZIM: massive EBITDA swings, drydocking capex, vessel impairments."""
    tickers = ["ZIM"]
    ltm = {
        "ZIM": _query_result(
            "ZIM",
            _ltm_metrics(
                revenue=_cited(8_000_000_000, "revenue", "USD"),
                net_income=_cited(2_500_000_000, "net_income", "USD"),
                ebitda=_cited(4_000_000_000, "ebitda", "USD"),
                operating_income=_cited(3_000_000_000, "operating_income", "USD"),
                depreciation_amortization=_cited(1_000_000_000, "depreciation_amortization", "USD"),
                total_debt=_cited(5_000_000_000, "total_debt", "USD"),
                cash=_cited(3_000_000_000, "cash", "USD"),
                stockholders_equity=_cited(4_000_000_000, "stockholders_equity", "USD"),
            ),
        )
    }
    # Prior year had much lower EBITDA (cyclical)
    growth_metrics = _growth_metrics()
    growth_metrics["ebitda"] = _cited(1_500_000_000, "ebitda", "USD")
    growth_metrics["net_income"] = _cited(500_000_000, "net_income", "USD")
    growth = {"ZIM": _query_result("ZIM", growth_metrics, period="ltm-1")}
    market = {"ZIM": _snapshot("ZIM", price=25.0, shares=120_000_000)}

    results = await _run_analysis(tickers, ltm, growth, market)
    zim = results[0]
    assert zim.errors == []
    assert zim.multiples["ev_ebitda"].value is not None
    assert "ebitda_yoy" in zim.growth
    # EBITDA growth should be very large (167%)
    assert zim.growth["ebitda_yoy"].value > 1.0


@pytest.mark.asyncio
async def test_mining_commodity():
    """FCX: commodity sensitivity, impairment risk."""
    tickers = ["FCX"]
    ltm = {
        "FCX": _query_result(
            "FCX",
            _ltm_metrics(
                revenue=_cited(24_000_000_000, "revenue", "USD"),
                net_income=_cited(4_000_000_000, "net_income", "USD"),
                operating_income=_cited(6_000_000_000, "operating_income", "USD"),
                depreciation_amortization=_cited(2_500_000_000, "depreciation_amortization", "USD"),
                total_debt=_cited(10_000_000_000, "total_debt", "USD"),
                cash=_cited(5_000_000_000, "cash", "USD"),
                stockholders_equity=_cited(20_000_000_000, "stockholders_equity", "USD"),
            ),
        )
    }
    growth = {"FCX": _query_result("FCX", _growth_metrics(), period="ltm-1")}
    market = {"FCX": _snapshot("FCX", price=45.0, shares=1_440_000_000)}

    results = await _run_analysis(tickers, ltm, growth, market)
    fcx = results[0]
    assert fcx.errors == []
    assert fcx.ev_bridge.enterprise_value.value is not None
    assert fcx.multiples["ev_ebitda"].value is not None
    assert fcx.multiples["pe"].value is not None


@pytest.mark.asyncio
async def test_bank_pair_jpm_wfc():
    """JPM + WFC: interest income, provisions, bank-specific leverage."""
    tickers = ["JPM", "WFC"]
    ltm = {}
    growth = {}
    market = {}

    for ticker, (price, shares, rev, ni) in {
        "JPM": (220.0, 2_800_000_000, 175_000_000_000, 55_000_000_000),
        "WFC": (65.0, 3_600_000_000, 82_000_000_000, 18_000_000_000),
    }.items():
        ltm[ticker] = _query_result(
            ticker,
            _ltm_metrics(
                revenue=_cited(rev, "revenue", "USD"),
                net_income=_cited(ni, "net_income", "USD"),
                ebitda=None,  # Banks don't have meaningful EBITDA
                operating_income=None,
                depreciation_amortization=None,
                total_debt=_cited(300_000_000_000, "total_debt", "USD"),
                cash=_cited(500_000_000_000, "cash", "USD"),
                stockholders_equity=_cited(320_000_000_000, "stockholders_equity", "USD"),
            ),
        )
        growth[ticker] = _query_result(ticker, _growth_metrics(), period="ltm-1")
        market[ticker] = _snapshot(ticker, price=price, shares=shares)

    results = await _run_analysis(tickers, ltm, growth, market)
    for result in results:
        assert result.errors == []
        assert result.multiples["pe"].value is not None
        assert result.multiples["price_book"].value is not None
        # EBITDA-based multiples should be None for banks
        assert result.multiples["ev_ebitda"].value is None


@pytest.mark.asyncio
async def test_brazilian_adr_pbr():
    """PBR: BRL currency, commodity + FX double exposure."""
    tickers = ["PBR"]
    ltm = {"PBR": _query_result("PBR", _ltm_metrics(unit="BRL"))}
    growth = {"PBR": _query_result("PBR", _growth_metrics(unit="BRL"), period="ltm-1")}
    market = {"PBR": _snapshot("PBR", price=14.0, shares=6_300_000_000)}

    results = await _run_analysis(tickers, ltm, growth, market)
    pbr = results[0]
    assert pbr.errors == []
    # EV should be None due to BRL/USD currency mismatch
    assert pbr.ev_bridge.enterprise_value.value is None
    assert any("cannot mix currencies" in w for w in pbr.ev_bridge.enterprise_value.warnings)
    # Operating ratios should still work (same-currency numerator/denominator)
    assert "rd_pct_revenue" in pbr.operating


@pytest.mark.asyncio
async def test_japanese_adr_hmc():
    """HMC: JPY currency, March FY end."""
    tickers = ["HMC"]
    ltm = {"HMC": _query_result("HMC", _ltm_metrics(unit="JPY"))}
    growth = {"HMC": _query_result("HMC", _growth_metrics(unit="JPY"), period="ltm-1")}
    market = {"HMC": _snapshot("HMC", price=35.0, shares=1_700_000_000)}

    results = await _run_analysis(tickers, ltm, growth, market)
    hmc = results[0]
    assert hmc.errors == []
    # EV should be None due to JPY/USD currency mismatch
    assert hmc.ev_bridge.enterprise_value.value is None
    assert any("cannot mix currencies" in w for w in hmc.ev_bridge.enterprise_value.warnings)


@pytest.mark.asyncio
async def test_pre_profit_ev_rivn():
    """RIVN: deep losses, negative PE throughout."""
    tickers = ["RIVN"]
    ltm = {
        "RIVN": _query_result(
            "RIVN",
            _ltm_metrics(
                revenue=_cited(5_000_000_000, "revenue", "USD"),
                net_income=_cited(-5_800_000_000, "net_income", "USD"),
                operating_income=_cited(-5_000_000_000, "operating_income", "USD"),
                free_cash_flow=_cited(-6_000_000_000, "free_cash_flow", "USD"),
                stockholders_equity=_cited(8_000_000_000, "stockholders_equity", "USD"),
                total_debt=_cited(5_000_000_000, "total_debt", "USD"),
                cash=_cited(7_000_000_000, "cash", "USD"),
            ),
        )
    }
    growth = {"RIVN": _query_result("RIVN", _growth_metrics(), period="ltm-1")}
    market = {"RIVN": _snapshot("RIVN", price=15.0, shares=1_000_000_000)}

    results = await _run_analysis(tickers, ltm, growth, market)
    rivn = results[0]
    assert rivn.errors == []
    assert rivn.multiples["pe"].value is not None
    assert rivn.multiples["pe"].value < 0
    assert any("Negative denominator" in w for w in rivn.multiples["pe"].warnings)
    assert rivn.multiples["ev_revenue"].value is not None


@pytest.mark.asyncio
async def test_saas_high_sbc_ddog():
    """DDOG: SBC-heavy SaaS, adjusted vs GAAP EBITDA gap."""
    tickers = ["DDOG"]
    ltm = {
        "DDOG": _query_result(
            "DDOG",
            _ltm_metrics(
                revenue=_cited(2_600_000_000, "revenue", "USD"),
                net_income=_cited(300_000_000, "net_income", "USD"),
                ebitda=_cited(300_000_000, "ebitda", "USD"),  # OI 200M + D&A 100M
                operating_income=_cited(200_000_000, "operating_income", "USD"),
                depreciation_amortization=_cited(100_000_000, "depreciation_amortization", "USD"),
                stock_based_compensation=_cited(600_000_000, "stock_based_compensation", "USD"),
                total_debt=_cited(1_000_000_000, "total_debt", "USD"),
                cash=_cited(2_500_000_000, "cash", "USD"),
                stockholders_equity=_cited(3_000_000_000, "stockholders_equity", "USD"),
                rd_expense=_cited(800_000_000, "rd_expense", "USD"),
                sga_expense=_cited(600_000_000, "sga_expense", "USD"),
            ),
        )
    }
    growth = {"DDOG": _query_result("DDOG", _growth_metrics(), period="ltm-1")}
    market = {"DDOG": _snapshot("DDOG", price=130.0, shares=330_000_000)}

    results = await _run_analysis(tickers, ltm, growth, market)
    ddog = results[0]
    assert ddog.errors == []
    assert ddog.multiples["ev_ebitda"].value is not None
    # Adjusted EBITDA margin (34.6%) should be higher than GAAP EBITDA margin (11.5%)
    has_both = "adjusted_ebitda_margin" in ddog.operating and "ebitda_margin" in ddog.operating
    if has_both:
        adj = ddog.operating["adjusted_ebitda_margin"].value
        gaap = ddog.operating["ebitda_margin"].value
        assert adj > gaap


@pytest.mark.asyncio
async def test_negative_equity_sbux():
    """SBUX: negative equity from aggressive buybacks."""
    tickers = ["SBUX"]
    ltm = {
        "SBUX": _query_result(
            "SBUX",
            _ltm_metrics(
                revenue=_cited(36_000_000_000, "revenue", "USD"),
                net_income=_cited(4_000_000_000, "net_income", "USD"),
                stockholders_equity=_cited(-8_000_000_000, "stockholders_equity", "USD"),
                total_debt=_cited(15_000_000_000, "total_debt", "USD"),
            ),
        )
    }
    growth = {"SBUX": _query_result("SBUX", _growth_metrics(), period="ltm-1")}
    market = {"SBUX": _snapshot("SBUX", price=100.0, shares=1_100_000_000)}

    results = await _run_analysis(tickers, ltm, growth, market)
    sbux = results[0]
    assert sbux.errors == []
    assert sbux.multiples["price_book"].value < 0
    assert any("Negative denominator" in w for w in sbux.multiples["price_book"].warnings)
    # EV should still be computable
    assert sbux.ev_bridge.enterprise_value.value is not None


@pytest.mark.asyncio
async def test_ford_captive_finance_low_debt():
    """Ford: low resolved debt vs high liabilities. EV computed but debt is suspect."""
    tickers = ["F"]
    ltm = {
        "F": _query_result(
            "F",
            _ltm_metrics(
                revenue=_cited(175_000_000_000, "revenue", "USD"),
                net_income=_cited(1_800_000_000, "net_income", "USD"),
                total_debt=_cited(291_000_000, "total_debt", "USD"),  # Suspiciously low
                cash=_cited(25_000_000_000, "cash", "USD"),
                stockholders_equity=_cited(40_000_000_000, "stockholders_equity", "USD"),
            ),
        )
    }
    growth = {"F": _query_result("F", _growth_metrics(), period="ltm-1")}
    market = {"F": _snapshot("F", price=12.0, shares=4_000_000_000)}

    results = await _run_analysis(tickers, ltm, growth, market)
    f_result = results[0]
    assert f_result.errors == []
    assert f_result.ev_bridge.enterprise_value.value is not None
    # EV with only $291M debt - $25B cash = negative net debt
    assert f_result.ev_bridge.net_debt.value < 0


@pytest.mark.asyncio
async def test_consumer_tech_aapl_large_buyback():
    """AAPL: Sep FY, massive buybacks, huge operating leverage."""
    tickers = ["AAPL"]
    ltm = {
        "AAPL": _query_result(
            "AAPL",
            _ltm_metrics(
                revenue=_cited(390_000_000_000, "revenue", "USD"),
                net_income=_cited(100_000_000_000, "net_income", "USD"),
                operating_income=_cited(120_000_000_000, "operating_income", "USD"),
                depreciation_amortization=_cited(
                    11_000_000_000, "depreciation_amortization", "USD"
                ),
                total_debt=_cited(110_000_000_000, "total_debt", "USD"),
                cash=_cited(30_000_000_000, "cash", "USD"),
                marketable_securities=_cited(60_000_000_000, "marketable_securities", "USD"),
                stockholders_equity=_cited(60_000_000_000, "stockholders_equity", "USD"),
            ),
        )
    }
    growth = {"AAPL": _query_result("AAPL", _growth_metrics(), period="ltm-1")}
    market = {"AAPL": _snapshot("AAPL", price=230.0, shares=15_000_000_000)}

    results = await _run_analysis(tickers, ltm, growth, market)
    aapl = results[0]
    assert aapl.errors == []
    assert aapl.ev_bridge.enterprise_value.value is not None
    assert aapl.multiples["pe"].value is not None
    assert aapl.multiples["ev_ebitda"].value is not None
