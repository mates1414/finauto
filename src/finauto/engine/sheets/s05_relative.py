"""05_Relative_Valuation — peer multiples computed purely by formula from the
raw peer data on 03, plus three implied-price tracks that each enforce the
EV -> -NetDebt -> Equity -> /Shares bridge."""

from __future__ import annotations

from dataclasses import dataclass

from ..context import BuildContext
from ..formulas import S03, a1, blank_guard, iferror, sref
from .s02_historicals import Sheet2Layout
from .s03_wacc import Sheet3Layout

_PEER_FIRST_ROW = 4
_COL_TICKER, _COL_EV, _COL_EV_EBITDA, _COL_EV_SALES, _COL_PE = 0, 1, 2, 3, 4


@dataclass
class Sheet5Layout:
    price_ev_ebitda_cell: str
    price_ev_sales_cell: str
    price_pe_cell: str


def build(ws, ctx: BuildContext, l2: Sheet2Layout, l3: Sheet3Layout) -> Sheet5Layout:
    st, L = ctx.styles, ctx.L
    n = l3.n_peers
    first = _PEER_FIRST_ROW
    median_row = first + n

    ws.set_column(0, 0, 36)
    ws.set_column(1, 4, 15)
    ws.write(0, 0, L("s05.title"), st.title)
    ws.merge_range(2, 0, 2, 4, L("s05.peer_header"), st.section)
    for c, key in enumerate(
        ["s03.col_ticker", "s05.col_ev", "s05.col_ev_ebitda", "s05.col_ev_sales", "s05.col_pe"]
    ):
        ws.write(3, c, L(key), st.colhead)

    def guarded_ratio(num: str, den: str) -> str:
        """num/den blanked when either side is missing or den is non-positive
        (negative-earnings P/E and zero-EBITDA multiples are meaningless)."""
        cond = f'OR({num}="",{den}="",{den}<=0)'
        return iferror(f'IF({cond},"",{num}/{den})')

    for i in range(n):
        r = first + i
        mc = sref(S03, l3.peer_a1("mktcap", i))
        debt = sref(S03, l3.peer_a1("debt", i))
        cash = sref(S03, l3.peer_a1("cash", i))
        ebitda = sref(S03, l3.peer_a1("ebitda", i))
        sales = sref(S03, l3.peer_a1("sales", i))
        ni = sref(S03, l3.peer_a1("ni", i))
        ev = a1(r, _COL_EV)

        ws.write_formula(r, _COL_TICKER, f"={sref(S03, l3.peer_a1('ticker', i))}", st.label)
        # EV = market cap + gross debt - cash (blank debt/cash coerce to 0)
        ws.write_formula(r, _COL_EV, f'=IF({mc}="","",{mc}+{debt}-{cash})', st.num)
        ws.write_formula(r, _COL_EV_EBITDA, f"={guarded_ratio(ev, ebitda)}", st.mult)
        ws.write_formula(r, _COL_EV_SALES, f"={guarded_ratio(ev, sales)}", st.mult)
        ws.write_formula(r, _COL_PE, f"={guarded_ratio(mc, ni)}", st.mult)

    ws.write(median_row, 0, L("s05.median"), st.label_bold)
    median_cells: dict[str, str] = {}
    for key, col in (("ev_ebitda", _COL_EV_EBITDA), ("ev_sales", _COL_EV_SALES), ("pe", _COL_PE)):
        if n > 0:
            rng = f"{a1(first, col)}:{a1(first + n - 1, col)}"
            ws.write_formula(median_row, col, f"={iferror(f'MEDIAN({rng})')}", st.mult)
        else:
            # no peers: medians become manual multiple inputs
            ws.write_blank(median_row, col, None, st.input_mult)
        median_cells[key] = a1(median_row, col, abs_row=True, abs_col=True)

    def track(start: int, header_key: str, metric_key: str, metric_ref: str,
              multiple_cell: str, with_net_debt: bool) -> str:
        """Write one implied-price block; returns the implied price cell (abs)."""
        ws.merge_range(start, 0, start, 1, L(header_key), st.section)
        r_metric, r_mult, r_next = start + 1, start + 2, start + 3
        metric = a1(r_metric, 1)
        mult = a1(r_mult, 1)
        ws.write(r_metric, 0, L(metric_key), st.label)
        ws.write_formula(r_metric, 1, f"={metric_ref}", st.num)
        ws.write(r_mult, 0, L("s05.median_multiple"), st.label)
        ws.write_formula(r_mult, 1, f"={multiple_cell}", st.mult)

        if with_net_debt:
            r_ev, r_nd, r_eq, r_price = r_next, r_next + 1, r_next + 2, r_next + 3
            ev_c = a1(r_ev, 1)
            nd_c = a1(r_nd, 1)
            ws.write(r_ev, 0, L("s05.implied_ev"), st.label)
            ws.write_formula(r_ev, 1, f"={blank_guard([metric, mult], f'{metric}*{mult}')}", st.num)
            ws.write(r_nd, 0, L("s05.net_debt"), st.label)
            ws.write_formula(r_nd, 1, f"={l2.net_debt_expr()}", st.num)
            ws.write(r_eq, 0, L("s05.implied_equity"), st.label_bold)
            ws.write_formula(r_eq, 1, f'=IF({ev_c}="","",{ev_c}-{nd_c})', st.num_bold)
        else:
            r_eq, r_price = r_next, r_next + 1
            ws.write(r_eq, 0, L("s05.implied_equity"), st.label_bold)
            ws.write_formula(
                r_eq, 1, f"={blank_guard([metric, mult], f'{metric}*{mult}')}", st.num_bold
            )
        eq_c = a1(r_eq, 1)
        ws.write(r_price, 0, L("s05.implied_price"), st.label_bold)
        ws.write_formula(
            r_price, 1,
            f'=IF({eq_c}="","",{iferror(f"{eq_c}/SharesOut")})',
            st.price_bold,
        )
        return a1(r_price, 1, abs_row=True, abs_col=True)

    t1 = median_row + 2
    price_ebitda = track(
        t1, "s05.track_ev_ebitda", "s05.target_metric_ebitda",
        l2.latest("ebitda"), median_cells["ev_ebitda"], with_net_debt=True,
    )
    t2 = t1 + 8
    price_sales = track(
        t2, "s05.track_ev_sales", "s05.target_metric_sales",
        l2.latest("revenue"), median_cells["ev_sales"], with_net_debt=True,
    )
    t3 = t2 + 8
    price_pe = track(
        t3, "s05.track_pe", "s05.target_metric_ni",
        l2.latest("net_income"), median_cells["pe"], with_net_debt=False,
    )

    return Sheet5Layout(
        price_ev_ebitda_cell=price_ebitda,
        price_ev_sales_cell=price_sales,
        price_pe_cell=price_pe,
    )
