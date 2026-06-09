"""Pydantic data contracts shared by every pipeline stage.

All monetary fields are Optional floats: the LLM extractor fills what it can
find, and the Excel engine degrades missing values to blank cells guarded by
IFERROR formulas.
"""

from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field

Number = Optional[float]

UNIT_MULTIPLIERS: dict[str, float] = {
    "units": 1.0,
    "thousands": 1_000.0,
    "millions": 1_000_000.0,
}


class IncomeStatement(BaseModel):
    revenue: Number = None
    cogs: Number = Field(None, description="Cost of goods sold, as a positive number")
    gross_profit: Number = None
    sga: Number = Field(None, description="Operating/SG&A expenses, as a positive number")
    ebitda: Number = None
    depreciation_amortization: Number = None
    ebit: Number = None
    net_interest_expense: Number = Field(
        None, description="Net financing expense; positive means net expense"
    )
    net_income: Number = None


class BalanceSheet(BaseModel):
    cash_and_equivalents: Number = None
    total_current_assets: Number = None
    total_assets: Number = None
    short_term_debt: Number = Field(None, description="Short-term financial borrowings")
    long_term_debt: Number = Field(None, description="Long-term financial borrowings")
    lease_liabilities: Number = Field(
        None, description="Short + long term lease obligations (IFRS 16)"
    )
    total_liabilities: Number = None
    retained_earnings: Number = None
    total_equity: Number = None


class CashFlowItems(BaseModel):
    depreciation_amortization: Number = None
    capex: Number = Field(None, description="Capital expenditures, as a positive number")


class FiscalYearData(BaseModel):
    year: int
    income_statement: IncomeStatement = Field(default_factory=IncomeStatement)
    balance_sheet: BalanceSheet = Field(default_factory=BalanceSheet)
    cash_flow: CashFlowItems = Field(default_factory=CashFlowItems)


class CompanyFinancials(BaseModel):
    ticker: str
    name: Optional[str] = None
    currency: str = "TRY"
    units: Literal["units", "thousands", "millions"] = "thousands"
    sector_hint: Optional[str] = None
    source: Optional[str] = None
    periods: list[FiscalYearData] = Field(default_factory=list)

    def sorted_periods(self) -> list[FiscalYearData]:
        return sorted(self.periods, key=lambda p: p.year)

    @property
    def latest(self) -> FiscalYearData:
        return self.sorted_periods()[-1]

    def normalized(self) -> "CompanyFinancials":
        """Return a deep copy with all monetary values in absolute currency units."""
        copy = self.model_copy(deep=True)
        mult = UNIT_MULTIPLIERS[self.units]
        if mult != 1.0:
            for p in copy.periods:
                for section in (p.income_statement, p.balance_sheet, p.cash_flow):
                    for fname in type(section).model_fields:
                        v = getattr(section, fname)
                        if isinstance(v, (int, float)):
                            setattr(section, fname, float(v) * mult)
        copy.units = "units"
        return copy


SNAPSHOT_NUMERIC_FIELDS = (
    "price",
    "shares_outstanding",
    "market_cap",
    "beta",
    "total_debt",
    "cash",
    "ebitda",
    "revenue",
    "net_income",
)


class TickerSnapshot(BaseModel):
    ticker: str
    name: Optional[str] = None
    currency: Optional[str] = None
    price: Number = None
    shares_outstanding: Number = None
    market_cap: Number = None
    beta: Number = None
    total_debt: Number = Field(None, description="Gross debt incl. lease obligations")
    cash: Number = None
    ebitda: Number = None
    revenue: Number = None
    net_income: Number = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    as_of: date = Field(default_factory=date.today)

    def missing_fields(self) -> list[str]:
        return [f for f in SNAPSHOT_NUMERIC_FIELDS if getattr(self, f) is None]


class MarketData(BaseModel):
    target: TickerSnapshot
    peers: list[TickerSnapshot] = Field(default_factory=list)


class Assumptions(BaseModel):
    """User-tunable valuation inputs; defaults are placeholders meant to be
    overridden via assumptions.yaml, CLI flags, or derived from historicals."""

    risk_free_rate: float = 0.25
    equity_risk_premium: float = 0.055
    country_risk_premium: float = 0.045
    tax_rate: float = 0.25
    fx_rate: float = Field(1.0, description="Model currency per 1 unit of target currency, e.g. EUR/TRY")
    growth_stage1: float = 0.20
    growth_stage2: float = 0.10
    terminal_growth: float = 0.03
    ebit_margin: float = 0.12
    capex_pct_sales: float = 0.06
    nwc_pct_sales: float = 0.02
    da_pct_sales: float = 0.05
    rd_spread: float = Field(0.04, description="Cost-of-debt spread over the risk-free rate fallback")
    weight_dcf: float = 0.70
    weight_multiples: float = 0.30
    signal_threshold: float = 0.15


class ValuationInputs(BaseModel):
    financials: CompanyFinancials
    market: MarketData
    assumptions: Assumptions = Field(default_factory=Assumptions)
    locale: Literal["tr", "en"] = "tr"
