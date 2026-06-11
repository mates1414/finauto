"""04_DCF_Model — 10-year FCFF forecast. Zero hardcoded financial values:
the base year links to 02, every driver reads a defined name from 01."""

from __future__ import annotations

from dataclasses import dataclass

from ..context import BuildContext
from ..formulas import a1, iferror
from .s02_historicals import Sheet2Layout

# 0-based rows
ROWS: dict[str, int] = {
    "year": 2,
    "t": 3,
    "revenue": 4,
    "ebit": 5,
    "nopat": 6,
    "da": 7,
    "capex": 8,
    "dnwc": 9,
    "fcff": 10,
    "df": 11,
    "pv": 12,
    "fcff_margin": 13,
    "sum_pv": 14,
    "tv": 15,
    "pv_tv": 16,
    "ev": 17,
    "net_debt": 18,
    "equity_value": 19,
    "implied_price": 20,
}

_BASE_COL = 1  # column B = Year 0
_LAST_COL = 11  # column L = Year 10


@dataclass
class Sheet4Layout:
    implied_price_cell: str  # absolute local ref


def build(ws, ctx: BuildContext, l2: Sheet2Layout) -> Sheet4Layout:
    st, L = ctx.styles, ctx.L
    base_year = ctx.fin.latest.year

    ws.set_column(0, 0, 42)
    ws.set_column(_BASE_COL, _LAST_COL, 14)
    ws.write(0, 0, L("s04.title"), st.title)

    label_order = [
        "year", "t", "revenue", "ebit", "nopat", "da", "capex", "dnwc",
        "fcff", "df", "pv", "fcff_margin", "sum_pv", "tv", "pv_tv", "ev", "net_debt",
        "equity_value", "implied_price",
    ]
    bold = {"fcff", "sum_pv", "ev", "equity_value", "implied_price"}
    for key in label_order:
        fmt = st.label_bold if key in bold else st.label
        head = st.colhead if key == "year" else fmt
        ws.write(ROWS[key], 0, L(f"s04.{key}"), head)

    for c in range(_BASE_COL, _LAST_COL + 1):
        t = c - _BASE_COL
        ws.write_number(ROWS["year"], c, base_year + t, st.year_head)
        ws.write_number(ROWS["t"], c, t, st.int_center)

    # Year 0 revenue links to the latest historical year on 02
    ws.write_formula(ROWS["revenue"], _BASE_COL, f"={l2.latest('revenue')}", st.num)

    for c in range(_BASE_COL + 1, _LAST_COL + 1):
        t = c - _BASE_COL
        rev = a1(ROWS["revenue"], c)
        prev_rev = a1(ROWS["revenue"], c - 1)
        ebit = a1(ROWS["ebit"], c)
        nopat = a1(ROWS["nopat"], c)
        da = a1(ROWS["da"], c)
        capex = a1(ROWS["capex"], c)
        dnwc = a1(ROWS["dnwc"], c)
        fcff = a1(ROWS["fcff"], c)
        df = a1(ROWS["df"], c)
        t_ref = a1(ROWS["t"], c)

        growth = "Growth1" if t <= 5 else "Growth2"
        ws.write_formula(ROWS["revenue"], c, f"={prev_rev}*(1+{growth})", st.num)
        ws.write_formula(ROWS["ebit"], c, f"={rev}*EBITMargin", st.num)
        ws.write_formula(ROWS["nopat"], c, f"={ebit}*(1-TaxRate)", st.num)
        ws.write_formula(ROWS["da"], c, f"={rev}*DAPct", st.num)
        ws.write_formula(ROWS["capex"], c, f"={rev}*CapExPct", st.num)
        ws.write_formula(ROWS["dnwc"], c, f"=({rev}-{prev_rev})*NWCPct", st.num)
        ws.write_formula(ROWS["fcff"], c, f"={nopat}+{da}-{capex}-{dnwc}", st.num_bold)
        ws.write_formula(ROWS["df"], c, f"={iferror(f'1/(1+WACC)^{t_ref}')}", st.factor)
        ws.write_formula(ROWS["pv"], c, f"={iferror(f'{fcff}*{df}')}", st.num)
        ws.write_formula(ROWS["fcff_margin"], c, f"={iferror(f'{fcff}/{rev}')}", st.pct)

    pv_first = a1(ROWS["pv"], _BASE_COL + 1)
    pv_last = a1(ROWS["pv"], _LAST_COL)
    fcff_last = a1(ROWS["fcff"], _LAST_COL)
    df_last = a1(ROWS["df"], _LAST_COL)
    # column B summary cells
    sum_pv = a1(ROWS["sum_pv"], 1)
    tv = a1(ROWS["tv"], 1)
    pv_tv = a1(ROWS["pv_tv"], 1)
    ev = a1(ROWS["ev"], 1)
    net_debt = a1(ROWS["net_debt"], 1)
    equity = a1(ROWS["equity_value"], 1)

    ws.write_formula(ROWS["sum_pv"], 1, f"=SUM({pv_first}:{pv_last})", st.num_bold)
    # Gordon Growth terminal value; blanked when WACC is missing or <= g
    tv_expr = f"{fcff_last}*(1+TerminalGrowth)/(WACC-TerminalGrowth)"
    ws.write_formula(
        ROWS["tv"], 1,
        f'=IF(OR(WACC="",WACC<=TerminalGrowth),"",{iferror(tv_expr)})',
        st.num,
    )
    ws.write_formula(
        ROWS["pv_tv"], 1,
        f'=IF({tv}="","",{iferror(f"{tv}*{df_last}")})',
        st.num,
    )
    ws.write_formula(
        ROWS["ev"], 1,
        f'=IF({pv_tv}="","",{sum_pv}+{pv_tv})',
        st.num_bold,
    )
    ws.write_formula(ROWS["net_debt"], 1, f"={l2.net_debt_expr()}", st.num)
    ws.write_formula(
        ROWS["equity_value"], 1,
        f'=IF({ev}="","",{ev}-{net_debt})',
        st.num_bold,
    )
    ws.write_formula(
        ROWS["implied_price"], 1,
        f'=IF({equity}="","",{iferror(f"{equity}/SharesOut")})',
        st.price_bold,
    )

    return Sheet4Layout(
        implied_price_cell=a1(ROWS["implied_price"], 1, abs_row=True, abs_col=True)
    )
