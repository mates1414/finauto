"""03_WACC_Calculation — peer beta matrix + target capital structure.

This sheet hosts ALL hardcoded peer market data (the only other sheet allowed
to carry hardcoded values besides 02); 05_Relative_Valuation references it.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..context import BuildContext
from ..formulas import a1, blank_guard, iferror
from .s02_historicals import Sheet2Layout

# 0-based column order of the peer matrix
PEER_COLS: dict[str, int] = {
    "ticker": 0,
    "price": 1,
    "shares": 2,
    "mktcap": 3,
    "debt": 4,
    "cash": 5,
    "ebitda": 6,
    "sales": 7,
    "ni": 8,
    "beta": 9,
    "de": 10,
    "unlev": 11,
}

_PEER_FIRST_ROW = 4  # 0-based; row 3 holds the column heads


@dataclass
class Sheet3Layout:
    n_peers: int
    peer_first_row: int
    median_row: int
    wacc_cell: str  # absolute local ref, e.g. $B$25
    ke_cell: str
    rd_cell: str

    def peer_a1(self, col_key: str, i: int) -> str:
        """Absolute local A1 of peer i's cell (for cross-sheet use via sref)."""
        return a1(self.peer_first_row + i, PEER_COLS[col_key], abs_row=True, abs_col=True)


def build(ws, ctx: BuildContext, l2: Sheet2Layout) -> Sheet3Layout:
    st, L, a = ctx.styles, ctx.L, ctx.assumptions
    peers = ctx.market.peers
    n = len(peers)
    first = _PEER_FIRST_ROW
    median_row = first + n

    ws.set_column(0, 0, 14)
    ws.set_column(1, 11, 14)
    ws.write(0, 0, L("s03.title"), st.title)
    ws.merge_range(2, 0, 2, 11, L("s03.peer_header"), st.section)

    head_keys = [
        "s03.col_ticker", "s03.col_price", "s03.col_shares", "s03.col_mktcap",
        "s03.col_debt", "s03.col_cash", "s03.col_ebitda", "s03.col_sales",
        "s03.col_ni", "s03.col_beta", "s03.col_de", "s03.col_unlev",
    ]
    for c, key in enumerate(head_keys):
        ws.write(3, c, L(key), st.colhead)

    def write_val(row: int, col: int, value, fmt) -> None:
        if value is None:
            ws.write_blank(row, col, None, fmt)
        else:
            ws.write_number(row, col, value, fmt)

    for i, peer in enumerate(peers):
        r = first + i
        ws.write(r, PEER_COLS["ticker"], peer.ticker, st.label)
        write_val(r, PEER_COLS["price"], peer.price, st.price)
        write_val(r, PEER_COLS["shares"], peer.shares_outstanding, st.num)
        write_val(r, PEER_COLS["debt"], peer.total_debt, st.num)
        write_val(r, PEER_COLS["cash"], peer.cash, st.num)
        write_val(r, PEER_COLS["ebitda"], peer.ebitda, st.num)
        write_val(r, PEER_COLS["sales"], peer.revenue, st.num)
        write_val(r, PEER_COLS["ni"], peer.net_income, st.num)
        write_val(r, PEER_COLS["beta"], peer.beta, st.beta)

        price = a1(r, PEER_COLS["price"])
        shares = a1(r, PEER_COLS["shares"])
        mktcap = a1(r, PEER_COLS["mktcap"])
        debt = a1(r, PEER_COLS["debt"])
        beta = a1(r, PEER_COLS["beta"])
        de = a1(r, PEER_COLS["de"])
        # market cap from raw price x shares; yfinance market_cap kept implicit
        ws.write_formula(
            r, PEER_COLS["mktcap"],
            f"={blank_guard([price, shares], f'{price}*{shares}')}",
            st.num,
        )
        # MAX(0, debt) clamp: a cash-rich peer must not produce a negative D/E
        ws.write_formula(
            r, PEER_COLS["de"],
            f"={blank_guard([debt, mktcap], f'MAX(0,{debt})/{mktcap}')}",
            st.beta,
        )
        ws.write_formula(
            r, PEER_COLS["unlev"],
            f"={blank_guard([beta, de], f'{beta}/(1+(1-TaxRate)*{de})')}",
            st.beta,
        )

    ws.write(median_row, 0, L("s03.median"), st.label_bold)
    unlev_col = PEER_COLS["unlev"]
    if n > 0:
        rng = f"{a1(first, unlev_col)}:{a1(first + n - 1, unlev_col)}"
        ws.write_formula(median_row, unlev_col, f"={iferror(f'MEDIAN({rng})')}", st.beta)
    else:
        # no peers supplied: median slot becomes a manual beta input
        ws.write_number(median_row, unlev_col, 1.0, st.input_beta)
    median_beta = a1(median_row, unlev_col, abs_row=True, abs_col=True)

    # ---- target capital structure & WACC ----
    t0 = median_row + 2
    ws.merge_range(t0, 0, t0, 1, L("s03.target_header"), st.section)
    rows = {
        "mv_equity": t0 + 1,
        "mv_debt": t0 + 2,
        "weight_e": t0 + 3,
        "weight_d": t0 + 4,
        "target_de": t0 + 5,
        "relev_beta": t0 + 6,
        "ke": t0 + 7,
        "rd_spread": t0 + 8,
        "rd": t0 + 9,
        "wacc": t0 + 10,
    }
    for key, row in rows.items():
        fmt = st.label_bold if key == "wacc" else st.label
        ws.write(row, 0, L(f"s03.{key}"), fmt)

    e = a1(rows["mv_equity"], 1)
    d = a1(rows["mv_debt"], 1)
    we = a1(rows["weight_e"], 1)
    wd = a1(rows["weight_d"], 1)
    tde = a1(rows["target_de"], 1)
    relev = a1(rows["relev_beta"], 1)
    ke = a1(rows["ke"], 1)
    spread = a1(rows["rd_spread"], 1)
    rd = a1(rows["rd"], 1)

    ws.write_formula(rows["mv_equity"], 1, "=CurrentPrice*SharesOut", st.num)
    ws.write_formula(rows["mv_debt"], 1, f"={l2.gross_debt_expr()}", st.num)
    ws.write_formula(rows["weight_e"], 1, f"={iferror(f'{e}/({e}+{d})')}", st.pct)
    ws.write_formula(rows["weight_d"], 1, f"={iferror(f'{d}/({e}+{d})')}", st.pct)
    ws.write_formula(rows["target_de"], 1, f"={iferror(f'{d}/{e}')}", st.beta)
    ws.write_formula(
        rows["relev_beta"], 1,
        f"={blank_guard([median_beta, tde], f'{median_beta}*(1+(1-TaxRate)*{tde})')}",
        st.beta,
    )
    ws.write_formula(
        rows["ke"], 1,
        f'=IF({relev}="","",RiskFree+{relev}*ERP+CRP)',
        st.pct,
    )
    ws.write_number(rows["rd_spread"], 1, a.rd_spread, st.input_pct)

    # Rd from net interest expense / average gross debt, else Rf + spread
    interest = l2.latest("net_interest")
    if l2.prior_col is not None:
        avg_debt = f"(({l2.gross_debt_expr()})+({l2.gross_debt_expr(l2.prior_col)}))/2"
    else:
        avg_debt = f"({l2.gross_debt_expr()})"
    ws.write_formula(
        rows["rd"], 1,
        f'=IF({interest}="",RiskFree+{spread},'
        f"{iferror(f'{interest}/{avg_debt}', f'RiskFree+{spread}')})",
        st.pct,
    )
    ws.write_formula(
        rows["wacc"], 1,
        f'=IF(OR({ke}="",{rd}=""),"",{ke}*{we}+{rd}*(1-TaxRate)*{wd})',
        st.pct_bold,
    )

    def abs_b(row: int) -> str:
        return a1(row, 1, abs_row=True, abs_col=True)

    return Sheet3Layout(
        n_peers=n,
        peer_first_row=first,
        median_row=median_row,
        wacc_cell=abs_b(rows["wacc"]),
        ke_cell=abs_b(rows["ke"]),
        rd_cell=abs_b(rows["rd"]),
    )
