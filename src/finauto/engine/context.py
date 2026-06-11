from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import xlsxwriter

from ..schemas import Assumptions, CompanyFinancials, IndustryBeta, MarketData
from .styles import Styles


@dataclass
class BuildContext:
    wb: xlsxwriter.Workbook
    styles: Styles
    fin: CompanyFinancials  # normalized to absolute units and reconciled
    market: MarketData
    assumptions: Assumptions
    L: Callable[[str], str]  # label getter for the active locale
    industry_beta: IndustryBeta | None = None  # optional Damodaran sector beta
