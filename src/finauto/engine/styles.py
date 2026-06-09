"""Workbook cell formats. Convention: blue-on-cream cells are user inputs,
plain black cells are formulas/links — standard banker formatting."""

from __future__ import annotations

import xlsxwriter


class Styles:
    def __init__(self, wb: xlsxwriter.Workbook):
        base = {"font_name": "Calibri", "font_size": 10}
        self.title = wb.add_format({**base, "bold": True, "font_size": 14, "font_color": "#1F4E78"})
        self.section = wb.add_format({**base, "bold": True, "font_color": "#FFFFFF", "bg_color": "#1F4E78"})
        self.colhead = wb.add_format({**base, "bold": True, "bottom": 1, "align": "center"})
        self.year_head = wb.add_format({**base, "bold": True, "align": "center", "bottom": 1, "num_format": "0"})
        self.label = wb.add_format({**base})
        self.label_bold = wb.add_format({**base, "bold": True})
        self.note = wb.add_format({**base, "italic": True, "font_color": "#7F7F7F"})

        input_base = {
            **base,
            "font_color": "#0070C0",
            "bg_color": "#FFF7E6",
            "border": 1,
            "border_color": "#D9D9D9",
        }
        self.input_pct = wb.add_format({**input_base, "num_format": "0.00%"})
        self.input_num = wb.add_format({**input_base, "num_format": "#,##0"})
        self.input_price = wb.add_format({**input_base, "num_format": "#,##0.00"})
        self.input_rate = wb.add_format({**input_base, "num_format": "#,##0.0000"})
        self.input_beta = wb.add_format({**input_base, "num_format": "0.00"})
        self.input_mult = wb.add_format({**input_base, "num_format": '0.00"x"'})

        self.num = wb.add_format({**base, "num_format": "#,##0;[Red](#,##0)"})
        self.num_bold = wb.add_format({**base, "bold": True, "top": 1, "num_format": "#,##0;[Red](#,##0)"})
        self.pct = wb.add_format({**base, "num_format": "0.00%"})
        self.pct_bold = wb.add_format({**base, "bold": True, "top": 1, "num_format": "0.00%"})
        self.price = wb.add_format({**base, "num_format": "#,##0.00"})
        self.price_bold = wb.add_format({**base, "bold": True, "top": 1, "num_format": "#,##0.00"})
        self.mult = wb.add_format({**base, "num_format": '0.00"x"'})
        self.beta = wb.add_format({**base, "num_format": "0.00"})
        self.factor = wb.add_format({**base, "num_format": "0.0000"})
        self.int_center = wb.add_format({**base, "align": "center", "num_format": "0"})
        self.signal = wb.add_format(
            {**base, "bold": True, "align": "center", "font_size": 12, "bg_color": "#E2EFDA", "border": 1}
        )
