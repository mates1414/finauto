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
    sga: Number = Field(
        None, description="Operating/SG&A expenses, as a positive number"
    )
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
    capex: Number = Field(
        None, description="Capital expenditures, as a positive number"
    )


class FiscalYearData(BaseModel):
    year: int
    income_statement: IncomeStatement = Field(default_factory=IncomeStatement)
    balance_sheet: BalanceSheet = Field(default_factory=BalanceSheet)
    cash_flow: CashFlowItems = Field(default_factory=CashFlowItems)


def _merge_periods(base: FiscalYearData, other: FiscalYearData) -> FiscalYearData:
    """Combine two same-year periods, keeping the first non-None value per field.

    When several reports cover the same fiscal year (overlapping annual reports),
    `base` (seen first) wins; `other` only fills fields `base` left blank.
    """
    merged = base.model_copy(deep=True)
    for sec_name in ("income_statement", "balance_sheet", "cash_flow"):
        base_sec = getattr(merged, sec_name)
        other_sec = getattr(other, sec_name)
        for fname in type(base_sec).model_fields:
            if (
                getattr(base_sec, fname) is None
                and getattr(other_sec, fname) is not None
            ):
                setattr(base_sec, fname, getattr(other_sec, fname))
    return merged


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

    def deduped_periods(self) -> list[FiscalYearData]:
        """Merge any same-year periods into one, sorted by year ascending.

        Feeding several overlapping reports can yield duplicate fiscal years;
        this collapses them (first-seen wins, blanks filled from later copies)
        so the model gets exactly one column per distinct year.
        """
        by_year: dict[int, FiscalYearData] = {}
        for p in self.periods:
            existing = by_year.get(p.year)
            by_year[p.year] = _merge_periods(existing, p) if existing else p
        return [by_year[y] for y in sorted(by_year)]

    def with_deduped_periods(self) -> "CompanyFinancials":
        """Return a copy whose `periods` are deduped/merged by year."""
        return self.model_copy(update={"periods": self.deduped_periods()})

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


class IndustryBeta(BaseModel):
    """One row of Damodaran's industry beta table (a sector average).

    Used to source the WACC's unlevered beta from a robust sector reference
    instead of noisy per-ticker yfinance betas. The engine relevers this at the
    target's own D/E, so only the unlevered figures are load-bearing.
    """

    industry: str
    n_firms: Number = None
    levered_beta: Number = None
    de_ratio: Number = None
    tax_rate: Number = None
    unlevered_beta: Number = None
    cash_firm_value: Number = None
    unlevered_beta_cash_adj: Number = Field(
        None,
        description="Unlevered beta corrected for cash (Damodaran's pure-play beta)",
    )
    source: Optional[str] = None

    def chosen_unlevered(self, cash_adjusted: bool = True) -> float | None:
        """The unlevered beta to relever for WACC; cash-adjusted by default,
        falling back to the standard unlevered beta when it is missing."""
        if cash_adjusted and self.unlevered_beta_cash_adj is not None:
            return self.unlevered_beta_cash_adj
        return self.unlevered_beta


class Assumptions(BaseModel):
    """User-tunable valuation inputs; defaults are placeholders meant to be
    overridden via assumptions.yaml, CLI flags, or derived from historicals."""

    risk_free_rate: float = 0.25
    equity_risk_premium: float = 0.055
    country_risk_premium: float = 0.045
    tax_rate: float = 0.25
    fx_rate: float = Field(
        1.0, description="Model currency per 1 unit of target currency, e.g. EUR/TRY"
    )
    growth_stage1: float = 0.20
    growth_stage2: float = 0.10
    terminal_growth: float = 0.03
    ebit_margin: float = 0.12
    capex_pct_sales: float = 0.06
    nwc_pct_sales: float = 0.02
    da_pct_sales: float = 0.05
    rd_spread: float = Field(
        0.04, description="Cost-of-debt spread over the risk-free rate fallback"
    )
    weight_dcf: float = 0.70
    weight_multiples: float = 0.30
    signal_threshold: float = 0.15


class ValuationInputs(BaseModel):
    financials: CompanyFinancials
    market: MarketData
    assumptions: Assumptions = Field(default_factory=Assumptions)
    locale: Literal["tr", "en"] = "tr"
    industry_beta: Optional[IndustryBeta] = Field(
        None,
        description="Optional Damodaran sector beta sourcing the WACC's unlevered beta",
    )


# --- Phase 3 contracts (peer discovery, Excel round-trip, strategic report) ---
# These become API/DB payloads in the SaaS layer; keep them JSON-stable.


class PeerCandidate(BaseModel):
    """One peer proposed by the discovery stage, before/after live validation."""

    name: str
    ticker: Optional[str] = None
    exchange: Optional[str] = None
    rationale: Optional[str] = None
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="0..1 model confidence")
    resolved: bool = Field(False, description="True after a successful Yahoo snapshot")
    market_cap: Number = Field(
        None, description="Filled on resolution, for sanity sort"
    )


class PeerSuggestionSet(BaseModel):
    """Discovery output: validated candidates plus an audit trail of drops."""

    target: str
    candidates: list[PeerCandidate] = Field(default_factory=list)
    dropped: list[str] = Field(
        default_factory=list,
        description="'<name>: <reason>' for each dropped candidate",
    )
    source: Optional[str] = Field(
        None, description='e.g. "claude web_search 2026-06-13"'
    )

    def resolved(self) -> list[PeerCandidate]:
        """Resolved candidates, largest market cap first (None caps sort last)."""
        res = [c for c in self.candidates if c.resolved]
        return sorted(res, key=lambda c: (c.market_cap is None, -(c.market_cap or 0.0)))

    def tickers(self) -> list[str]:
        """Resolved tickers, market-cap ordered — feeds the existing peer path."""
        return [c.ticker for c in self.resolved() if c.ticker]


class EditNote(BaseModel):
    """One user correction discovered by diffing the edited workbook vs original."""

    path: str = Field(
        ..., description='Dotted path, e.g. "2025.income_statement.revenue"'
    )
    old: Number = None
    new: Number = None


class StrategicReport(BaseModel):
    """The grounded narrative produced from the corrected workbook."""

    ticker: str
    markdown: str
    grounded_figures: list[str] = Field(
        default_factory=list,
        description="Figures/cells the narrative is allowed to cite",
    )
    model: Optional[str] = None
