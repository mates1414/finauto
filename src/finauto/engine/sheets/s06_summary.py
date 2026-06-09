"""06_Valuation_Summary — executive dashboard: per-method target prices,
weighted blend, upside vs current price, and the automated trading signal."""

from __future__ import annotations

from ..context import BuildContext
from ..formulas import a1, iferror

# 0-based rows
_HEAD = 2
_R_DCF, _R_EV_EBITDA, _R_PE, _R_EV_SALES = 3, 4, 5, 6
_R_TARGET = 8
_R_CURRENT = 9
_R_UPSIDE = 10
_R_SIGNAL = 11
_R_FX = 13

TARGET_PRICE_CELL = a1(_R_TARGET, 1, abs_row=True, abs_col=True)


def build(ws, ctx: BuildContext) -> None:
    st, L = ctx.styles, ctx.L

    ws.set_column(0, 0, 32)
    ws.set_column(1, 2, 15)
    ws.write(0, 0, L("s06.title"), st.title)

    ws.write(_HEAD, 0, L("s06.col_method"), st.colhead)
    ws.write(_HEAD, 1, L("s06.col_price"), st.colhead)
    ws.write(_HEAD, 2, L("s06.col_weight"), st.colhead)

    methods = [
        (_R_DCF, "s06.method_dcf", "DCFImpliedPrice", "WeightDCF"),
        (_R_EV_EBITDA, "s06.method_ev_ebitda", "PriceEVEBITDA", "WeightMultiples*0.5"),
        (_R_PE, "s06.method_pe", "PricePE", "WeightMultiples*0.5"),
    ]
    for row, key, price_name, weight_expr in methods:
        ws.write(row, 0, L(key), st.label)
        ws.write_formula(row, 1, f"={price_name}", st.price)
        ws.write_formula(row, 2, f"={weight_expr}", st.pct)
    # EV/Sales shown for reference; weight is a manual input defaulting to 0
    ws.write(_R_EV_SALES, 0, L("s06.method_ev_sales"), st.label)
    ws.write_formula(_R_EV_SALES, 1, "=PriceEVSales", st.price)
    ws.write_number(_R_EV_SALES, 2, 0.0, st.input_pct)

    prices = f"{a1(_R_DCF, 1)}:{a1(_R_EV_SALES, 1)}"
    weights = f"{a1(_R_DCF, 2)}:{a1(_R_EV_SALES, 2)}"
    target = a1(_R_TARGET, 1)
    current = a1(_R_CURRENT, 1)
    upside = a1(_R_UPSIDE, 1)

    # weighted average over the methods that produced a price: N() turns blank
    # ("") results into 0 and the denominator keeps only available weights
    ws.write(_R_TARGET, 0, L("s06.weighted_target"), st.label_bold)
    weighted = (
        f'SUMPRODUCT(N({prices}),{weights})'
        f'/SUMPRODUCT(--({prices}<>""),{weights})'
    )
    ws.write_formula(_R_TARGET, 1, f"={iferror(weighted)}", st.price_bold)

    ws.write(_R_CURRENT, 0, L("s06.current_price"), st.label)
    ws.write_formula(_R_CURRENT, 1, "=CurrentPrice", st.price)

    ws.write(_R_UPSIDE, 0, L("s06.upside"), st.label_bold)
    ws.write_formula(_R_UPSIDE, 1, f"={iferror(f'{target}/{current}-1')}", st.pct_bold)

    buy, hold, sell = L("s06.signal_buy"), L("s06.signal_hold"), L("s06.signal_sell")
    ws.write(_R_SIGNAL, 0, L("s06.signal"), st.label_bold)
    ws.write_formula(
        _R_SIGNAL, 1,
        f'=IF({upside}="","",IF({upside}>SignalThreshold,"{buy}",'
        f'IF({upside}<-SignalThreshold,"{sell}","{hold}")))',
        st.signal,
    )

    ws.write(_R_FX, 0, L("s06.fx_price"), st.label)
    ws.write_formula(
        _R_FX, 1,
        f'=IF({target}="","",{iferror(f"{target}/FXRate")})',
        st.price,
    )
