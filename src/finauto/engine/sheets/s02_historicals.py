"""02_Historical_Financials — raw extracted data, years as columns.

Reported lines are hardcoded values; arithmetic lines (Gross Profit, EBIT,
Net Debt, derived ratios) are formulas so the statement stays self-consistent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from ...schemas import FiscalYearData
from ..context import BuildContext
from ..formulas import S02, a1, blank_guard, sref

# 0-based sheet rows. Each profitability margin sits directly under the line
# item it is computed from (e.g. gross_margin right below gross_profit), shown
# as an italic sub-row; period growth/CapEx ratios stay in the derived block.
ROWS: dict[str, int] = {
    "revenue": 4,
    "cogs": 5,
    "gross_profit": 6,
    "gross_margin": 7,
    "sga": 8,
    "ebitda": 9,
    "ebitda_margin": 10,
    "da": 11,
    "ebit": 12,
    "ebit_margin": 13,
    "net_interest": 14,
    "net_income": 15,
    "net_margin": 16,
    "cash": 19,
    "current_assets": 20,
    "total_assets": 21,
    "st_debt": 22,
    "lt_debt": 23,
    "leases": 24,
    "total_liabilities": 25,
    "retained": 26,
    "equity": 27,
    "capex": 30,
    "net_debt": 33,
    "rev_growth": 34,
    "capex_pct": 35,
}

# hardcoded data rows: row key -> value getter
_VALUE_GETTERS: dict[str, Callable[[FiscalYearData], float | None]] = {
    "revenue": lambda p: p.income_statement.revenue,
    "cogs": lambda p: p.income_statement.cogs,
    "sga": lambda p: p.income_statement.sga,
    "ebitda": lambda p: p.income_statement.ebitda,
    "da": lambda p: p.income_statement.depreciation_amortization,
    "net_interest": lambda p: p.income_statement.net_interest_expense,
    "net_income": lambda p: p.income_statement.net_income,
    "cash": lambda p: p.balance_sheet.cash_and_equivalents,
    "current_assets": lambda p: p.balance_sheet.total_current_assets,
    "total_assets": lambda p: p.balance_sheet.total_assets,
    "st_debt": lambda p: p.balance_sheet.short_term_debt,
    "lt_debt": lambda p: p.balance_sheet.long_term_debt,
    "leases": lambda p: p.balance_sheet.lease_liabilities,
    "total_liabilities": lambda p: p.balance_sheet.total_liabilities,
    "retained": lambda p: p.balance_sheet.retained_earnings,
    "equity": lambda p: p.balance_sheet.total_equity,
    "capex": lambda p: p.cash_flow.capex,
}


@dataclass
class Sheet2Layout:
    years: list[int]
    year_col: dict[int, int]  # fiscal year -> 0-based column
    rows: dict[str, int] = field(default_factory=lambda: dict(ROWS))

    @property
    def latest_col(self) -> int:
        return self.year_col[self.years[-1]]

    @property
    def prior_col(self) -> int | None:
        return self.year_col[self.years[-2]] if len(self.years) > 1 else None

    def ref(self, row_key: str, col_idx: int) -> str:
        """Absolute cross-sheet reference to a cell on this sheet."""
        return sref(S02, a1(self.rows[row_key], col_idx, abs_row=True, abs_col=True))

    def latest(self, row_key: str) -> str:
        return self.ref(row_key, self.latest_col)

    def net_debt_expr(self, col_idx: int | None = None) -> str:
        """Net debt (incl. leases) expression from this sheet's latest year."""
        c = self.latest_col if col_idx is None else col_idx
        return (
            f"{self.ref('st_debt', c)}+{self.ref('lt_debt', c)}"
            f"+{self.ref('leases', c)}-{self.ref('cash', c)}"
        )

    def gross_debt_expr(self, col_idx: int | None = None) -> str:
        c = self.latest_col if col_idx is None else col_idx
        return f"{self.ref('st_debt', c)}+{self.ref('lt_debt', c)}+{self.ref('leases', c)}"


def build(ws, ctx: BuildContext) -> Sheet2Layout:
    st, L = ctx.styles, ctx.L
    periods = ctx.fin.sorted_periods()
    years = [p.year for p in periods]
    year_col = {y: 1 + i for i, y in enumerate(years)}
    layout = Sheet2Layout(years=years, year_col=year_col)
    last_col = layout.latest_col

    ws.set_column(0, 0, 38)
    ws.set_column(1, last_col, 16)
    ws.write(0, 0, L("s02.title"), st.title)

    ws.write(2, 0, L("s02.item"), st.colhead)
    for y, c in year_col.items():
        ws.write_number(2, c, y, st.year_head)

    def section(row: int, key: str) -> None:
        ws.merge_range(row, 0, row, last_col, L(key), st.section)

    section(3, "s02.is_header")
    section(18, "s02.bs_header")
    section(29, "s02.cf_header")
    section(32, "s02.derived_header")

    label_keys = {
        "revenue": "s02.revenue", "cogs": "s02.cogs", "gross_profit": "s02.gross_profit",
        "sga": "s02.sga", "ebitda": "s02.ebitda", "da": "s02.da", "ebit": "s02.ebit",
        "net_interest": "s02.net_interest", "net_income": "s02.net_income",
        "cash": "s02.cash", "current_assets": "s02.current_assets",
        "total_assets": "s02.total_assets", "st_debt": "s02.st_debt",
        "lt_debt": "s02.lt_debt", "leases": "s02.leases",
        "total_liabilities": "s02.total_liabilities", "retained": "s02.retained",
        "equity": "s02.equity", "capex": "s02.capex", "net_debt": "s02.net_debt",
        "rev_growth": "s02.rev_growth", "ebit_margin": "s02.ebit_margin",
        "capex_pct": "s02.capex_pct", "gross_margin": "s02.gross_margin",
        "ebitda_margin": "s02.ebitda_margin", "net_margin": "s02.net_margin",
    }
    bold_rows = {"gross_profit", "ebitda", "ebit", "net_income", "total_assets", "equity", "net_debt"}
    margin_rows = {"gross_margin", "ebitda_margin", "ebit_margin", "net_margin"}
    for key, row in ROWS.items():
        if key in margin_rows:
            fmt = st.note  # italic gray: a sub-metric of the line above it
        elif key in bold_rows:
            fmt = st.label_bold
        else:
            fmt = st.label
        ws.write(row, 0, L(label_keys[key]), fmt)

    for p in periods:
        c = year_col[p.year]
        for key, getter in _VALUE_GETTERS.items():
            v = getter(p)
            if v is None:
                ws.write_blank(ROWS[key], c, None, st.num)
            else:
                ws.write_number(ROWS[key], c, v, st.num)

        rev = a1(ROWS["revenue"], c)
        ws.write_formula(
            ROWS["gross_profit"], c, f"={rev}-{a1(ROWS['cogs'], c)}", st.num
        )
        ws.write_formula(
            ROWS["ebit"], c, f"={a1(ROWS['ebitda'], c)}-{a1(ROWS['da'], c)}", st.num
        )
        ws.write_formula(
            ROWS["net_debt"], c,
            f"={a1(ROWS['st_debt'], c)}+{a1(ROWS['lt_debt'], c)}"
            f"+{a1(ROWS['leases'], c)}-{a1(ROWS['cash'], c)}",
            st.num_bold,
        )

        prior = c - 1 if c > 1 else None
        if prior is not None:
            prev_rev = a1(ROWS["revenue"], prior)
            ws.write_formula(
                ROWS["rev_growth"], c,
                f"={blank_guard([prev_rev, rev], f'{rev}/{prev_rev}-1')}",
                st.pct,
            )
        ebit = a1(ROWS["ebit"], c)
        capex = a1(ROWS["capex"], c)
        ws.write_formula(
            ROWS["ebit_margin"], c,
            f"={blank_guard([rev], f'{ebit}/{rev}')}",
            st.pct,
        )
        ws.write_formula(
            ROWS["capex_pct"], c,
            f"={blank_guard([capex, rev], f'{capex}/{rev}')}",
            st.pct,
        )
        gross = a1(ROWS["gross_profit"], c)
        ebitda = a1(ROWS["ebitda"], c)
        net_income = a1(ROWS["net_income"], c)
        ws.write_formula(
            ROWS["gross_margin"], c,
            f"={blank_guard([rev], f'{gross}/{rev}')}",
            st.pct,
        )
        ws.write_formula(
            ROWS["ebitda_margin"], c,
            f"={blank_guard([ebitda, rev], f'{ebitda}/{rev}')}",
            st.pct,
        )
        ws.write_formula(
            ROWS["net_margin"], c,
            f"={blank_guard([net_income, rev], f'{net_income}/{rev}')}",
            st.pct,
        )

    return layout
