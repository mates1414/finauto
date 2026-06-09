"""01_Assumptions — the control dashboard. Every input cell carries a
workbook-level defined name so downstream formulas read naturally."""

from __future__ import annotations

from ..context import BuildContext

# defined name -> absolute cell on this sheet (registered by the builder)
NAME_CELLS: dict[str, str] = {
    "RiskFree": "$B$4",
    "ERP": "$B$5",
    "CRP": "$B$6",
    "TaxRate": "$B$7",
    "FXRate": "$B$8",
    "Growth1": "$B$11",
    "Growth2": "$B$12",
    "TerminalGrowth": "$B$13",
    "EBITMargin": "$B$14",
    "CapExPct": "$B$15",
    "NWCPct": "$B$16",
    "DAPct": "$B$17",
    "WeightDCF": "$B$19",
    "WeightMultiples": "$B$20",
    "SignalThreshold": "$B$21",
    "CurrentPrice": "$B$23",
    "SharesOut": "$B$24",
}


def build(ws, ctx: BuildContext) -> None:
    st, L, a = ctx.styles, ctx.L, ctx.assumptions
    target = ctx.market.target

    ws.set_column(0, 0, 44)
    ws.set_column(1, 1, 18)
    ws.write(0, 0, L("s01.title"), st.title)

    def section(row: int, key: str) -> None:
        ws.merge_range(row, 0, row, 1, L(key), st.section)

    def inp(row: int, key: str, value, fmt) -> None:
        ws.write(row, 0, L(key), st.label)
        if value is None:
            ws.write_blank(row, 1, None, fmt)
        else:
            ws.write_number(row, 1, value, fmt)

    section(2, "s01.macro_header")
    inp(3, "s01.risk_free", a.risk_free_rate, st.input_pct)
    inp(4, "s01.erp", a.equity_risk_premium, st.input_pct)
    inp(5, "s01.crp", a.country_risk_premium, st.input_pct)
    inp(6, "s01.tax", a.tax_rate, st.input_pct)
    inp(7, "s01.fx", a.fx_rate, st.input_rate)

    section(9, "s01.growth_header")
    inp(10, "s01.growth1", a.growth_stage1, st.input_pct)
    inp(11, "s01.growth2", a.growth_stage2, st.input_pct)
    inp(12, "s01.terminal_growth", a.terminal_growth, st.input_pct)
    inp(13, "s01.ebit_margin", a.ebit_margin, st.input_pct)
    inp(14, "s01.capex_pct", a.capex_pct_sales, st.input_pct)
    inp(15, "s01.nwc_pct", a.nwc_pct_sales, st.input_pct)
    inp(16, "s01.da_pct", a.da_pct_sales, st.input_pct)

    section(17, "s01.weights_header")
    inp(18, "s01.weight_dcf", a.weight_dcf, st.input_pct)
    inp(19, "s01.weight_multiples", a.weight_multiples, st.input_pct)
    inp(20, "s01.signal_threshold", a.signal_threshold, st.input_pct)

    section(21, "s01.market_header")
    inp(22, "s01.current_price", target.price, st.input_price)
    inp(23, "s01.shares_out", target.shares_outstanding, st.input_num)
