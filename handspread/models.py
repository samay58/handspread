"""Core data models with full provenance chains.

Every number in a CompanyAnalysis traces back to either:
- MarketValue: a data point from a market vendor (Finnhub)
- CitedValue: a data point from SEC EDGAR (via edgarpack)
- ComputedValue: a derived calculation with formula + components
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from edgarpack.query.models import CitedValue, DerivedValue, QueryResult


class MarketValue(BaseModel):
    """A single market data point with vendor provenance."""

    metric: str
    value: float | int | None
    unit: str  # "USD", "shares", "USD/shares"
    vendor: str  # "finnhub"
    symbol: str
    endpoint: str  # "quote", "metric"
    as_of: datetime | None = None
    fetched_at: datetime
    raw: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @property
    def citation(self) -> str:
        ts = self.fetched_at.strftime("%Y-%m-%d %H:%M")
        return f"{self.vendor}:{self.endpoint} {self.symbol} @ {ts}"


class ComputedValue(BaseModel):
    """A derived calculation with formula and full component provenance."""

    metric: str
    value: float | int | None
    unit: str
    formula: str  # e.g. "market_cap + total_debt - cash"
    components: dict[str, Any] = Field(default_factory=dict)  # name -> SourceValue
    warnings: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class MarketSnapshot(BaseModel):
    """Current market data for a single company."""

    symbol: str
    company_name: str
    price: MarketValue
    shares_outstanding: MarketValue
    market_cap: ComputedValue

    @property
    def market_cap_value(self) -> float | None:
        return self.market_cap.value


class EVPolicy(BaseModel):
    """Configuration for enterprise value bridge construction."""

    cash_treatment: str = "subtract"  # "subtract" or "ignore"
    include_leases: bool = False
    subtract_equity_method_investments: bool = False
    debt_mode: str = "total_only"  # "total_only", "split", "total_plus_short"


class EVBridge(BaseModel):
    """Enterprise value bridge with full component provenance."""

    equity_value: ComputedValue | None = None
    total_debt: ComputedValue | CitedValue | None = None
    short_term_debt: ComputedValue | CitedValue | None = None
    cash_and_equivalents: ComputedValue | CitedValue | None = None
    marketable_securities: ComputedValue | CitedValue | None = None
    operating_lease_liabilities: ComputedValue | CitedValue | None = None
    preferred_stock: ComputedValue | CitedValue | None = None
    noncontrolling_interests: ComputedValue | CitedValue | None = None
    equity_method_investments: ComputedValue | CitedValue | None = None
    net_debt: ComputedValue | None = None
    enterprise_value: ComputedValue | None = None


class CompanyAnalysis(BaseModel):
    """Full analysis result for a single company. Every number is traceable."""

    symbol: str
    company_name: str
    cik: str
    period: str
    valuation_timestamp: datetime | None = None
    market: MarketSnapshot | None = None
    sec: QueryResult | None = None
    ev_bridge: EVBridge | None = None
    multiples: dict[str, ComputedValue] = Field(default_factory=dict)
    growth: dict[str, ComputedValue] = Field(default_factory=dict)
    operating: dict[str, ComputedValue] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
