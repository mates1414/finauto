"""Sheet name constants and raw-formula string helpers.

Conventions:
- helpers return formula *expressions* (no leading '='); sheet modules write
  f"={expr}" via write_formula.
- Excel function names are always English; Excel localizes display.
- every division must go through iferror()/blank_guard() so no #DIV/0! or
  #VALUE! ever reaches the user (enforced by tests).
"""

from __future__ import annotations

from xlsxwriter.utility import xl_col_to_name

S01 = "01_Assumptions"
S02 = "02_Historical_Financials"
S03 = "03_WACC_Calculation"
S04 = "04_DCF_Model"
S05 = "05_Relative_Valuation"
S06 = "06_Valuation_Summary"


def col(col_idx: int, abs_col: bool = False) -> str:
    return xl_col_to_name(col_idx, abs_col)


def a1(row: int, col_idx: int, abs_row: bool = False, abs_col: bool = False) -> str:
    """0-based (row, col) to A1 notation."""
    return f"{col(col_idx, abs_col)}{'$' if abs_row else ''}{row + 1}"


def sref(sheet: str, a1_ref: str) -> str:
    return f"'{sheet}'!{a1_ref}"


def iferror(expr: str, fallback: str = '""') -> str:
    return f"IFERROR({expr},{fallback})"


def blank_guard(refs: list[str], expr: str) -> str:
    """Blank out the result when any input cell is empty, and trap errors.

    Empty cells coerce to 0 in Excel arithmetic, which silently produces wrong
    numbers; this guard turns them into an empty string instead.
    """
    if len(refs) == 1:
        cond = f'{refs[0]}=""'
    else:
        cond = "OR(" + ",".join(f'{r}=""' for r in refs) + ")"
    return f'IF({cond},"",{iferror(expr)})'
