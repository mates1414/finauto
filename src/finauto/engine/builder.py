"""WorkbookBuilder — orchestrates the six interdependent sheets and registers
the workbook-level defined names that wire them together."""

from __future__ import annotations

from pathlib import Path

import xlsxwriter

from ..labels import label_getter
from ..schemas import ValuationInputs
from ..validation.sanity import reconcile_financials
from .context import BuildContext
from .formulas import S01, S02, S03, S04, S05, S06
from .sheets import (
    s01_assumptions,
    s02_historicals,
    s03_wacc,
    s04_dcf,
    s05_relative,
    s06_summary,
)
from .styles import Styles


class WorkbookBuilder:
    def __init__(self, inputs: ValuationInputs, out_path: Path | str):
        self.inputs = inputs
        self.out_path = Path(out_path)

    def build(self) -> Path:
        fin, _notes = reconcile_financials(self.inputs.financials.normalized())
        if not fin.periods:
            raise ValueError("financials contain no fiscal periods; nothing to model")

        wb = xlsxwriter.Workbook(str(self.out_path), {"nan_inf_to_errors": True})
        try:
            ctx = BuildContext(
                wb=wb,
                styles=Styles(wb),
                fin=fin,
                market=self.inputs.market,
                assumptions=self.inputs.assumptions,
                L=label_getter(self.inputs.locale),
                industry_beta=self.inputs.industry_beta,
            )
            ws1 = wb.add_worksheet(S01)
            ws2 = wb.add_worksheet(S02)
            ws3 = wb.add_worksheet(S03)
            ws4 = wb.add_worksheet(S04)
            ws5 = wb.add_worksheet(S05)
            ws6 = wb.add_worksheet(S06)

            s01_assumptions.build(ws1, ctx)
            for name, cell in s01_assumptions.NAME_CELLS.items():
                wb.define_name(name, f"='{S01}'!{cell}")

            l2 = s02_historicals.build(ws2, ctx)
            l3 = s03_wacc.build(ws3, ctx, l2)
            wb.define_name("WACC", f"='{S03}'!{l3.wacc_cell}")
            wb.define_name("CostOfEquity", f"='{S03}'!{l3.ke_cell}")
            wb.define_name("CostOfDebt", f"='{S03}'!{l3.rd_cell}")

            l4 = s04_dcf.build(ws4, ctx, l2)
            wb.define_name("DCFImpliedPrice", f"='{S04}'!{l4.implied_price_cell}")

            l5 = s05_relative.build(ws5, ctx, l2, l3)
            wb.define_name("PriceEVEBITDA", f"='{S05}'!{l5.price_ev_ebitda_cell}")
            wb.define_name("PriceEVSales", f"='{S05}'!{l5.price_ev_sales_cell}")
            wb.define_name("PricePE", f"='{S05}'!{l5.price_pe_cell}")

            s06_summary.build(ws6, ctx)
            wb.define_name("TargetPrice", f"='{S06}'!{s06_summary.TARGET_PRICE_CELL}")

            # Harden the round-trip surface: lock every sheet so only the blue
            # input cells (styled with locked=False) are editable. No password —
            # protection is a guard rail, trivially removed in Excel if needed.
            for ws in (ws1, ws2, ws3, ws4, ws5, ws6):
                ws.protect("", {"objects": False, "scenarios": False})

            ws6.activate()
        finally:
            wb.close()
        return self.out_path


def build_workbook(inputs: ValuationInputs, out_path: Path | str) -> Path:
    return WorkbookBuilder(inputs, out_path).build()
