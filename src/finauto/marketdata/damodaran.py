"""Read Damodaran's emerging-markets industry beta table (betaemerg.xls).

The legacy .xls (BIFF) format is read via xlrd. Parsing is split from file I/O
so the row-mapping logic is unit-testable without a binary fixture. The result
feeds the WACC's unlevered beta (see s03_wacc), relevered at the target's D/E.
"""

from __future__ import annotations

from pathlib import Path

from ..schemas import IndustryBeta

# 0-based column positions on the "Industry Averages" sheet. The layout has been
# stable for years; we still validate the header row before trusting it.
_COL = {
    "industry": 0,
    "n_firms": 1,
    "levered_beta": 2,
    "de_ratio": 3,
    "tax_rate": 4,
    "unlevered_beta": 5,
    "cash_firm_value": 6,
    "unlevered_beta_cash_adj": 7,
}
_SHEET = "Industry Averages"


class DamodaranError(ValueError):
    """The beta reference file could not be parsed or the industry was missing."""


def _num(row: list, idx: int) -> float | None:
    try:
        v = row[idx]
    except IndexError:
        return None
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_industry_rows(rows: list[list], source: str | None = None) -> dict[str, IndustryBeta]:
    """Map raw sheet rows (list of cell-value lists) to {industry: IndustryBeta}."""
    header = next(
        (i for i, r in enumerate(rows) if r and str(r[0]).strip().lower() == "industry name"),
        None,
    )
    if header is None:
        raise DamodaranError("could not find the 'Industry Name' header row in the beta sheet")

    table: dict[str, IndustryBeta] = {}
    for row in rows[header + 1 :]:
        name = str(row[0]).strip() if row else ""
        if not name:
            continue
        table[name] = IndustryBeta(
            industry=name,
            n_firms=_num(row, _COL["n_firms"]),
            levered_beta=_num(row, _COL["levered_beta"]),
            de_ratio=_num(row, _COL["de_ratio"]),
            tax_rate=_num(row, _COL["tax_rate"]),
            unlevered_beta=_num(row, _COL["unlevered_beta"]),
            cash_firm_value=_num(row, _COL["cash_firm_value"]),
            unlevered_beta_cash_adj=_num(row, _COL["unlevered_beta_cash_adj"]),
            source=source,
        )
    if not table:
        raise DamodaranError("no industry rows found below the header")
    return table


def load_industry_betas(path: Path | str) -> dict[str, IndustryBeta]:
    """Open the .xls beta reference and return {industry: IndustryBeta}."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"beta reference file not found: {path}")
    try:
        import xlrd
    except ImportError as e:  # pragma: no cover - exercised only without the dep
        raise ImportError(
            "reading the .xls beta file needs xlrd; install it with: pip install xlrd"
        ) from e

    book = xlrd.open_workbook(str(path))
    try:
        sheet = book.sheet_by_name(_SHEET)
    except xlrd.XLRDError as e:
        raise DamodaranError(f"'{_SHEET}' sheet not found in {path}") from e

    rows = [[sheet.cell_value(r, c) for c in range(sheet.ncols)] for r in range(sheet.nrows)]
    source = _source_label(rows)
    return parse_industry_rows(rows, source=source)


def _source_label(rows: list[list]) -> str:
    """Best-effort 'Damodaran Emerging Markets (updated YYYY-MM-DD)' label."""
    base = "Damodaran Emerging Markets"
    for r in rows[:6]:
        if r and str(r[0]).strip().lower().startswith("date updated") and len(r) > 1:
            serial = r[1]
            try:
                import xlrd

                d = xlrd.xldate.xldate_as_datetime(float(serial), 0).date()
                return f"{base} (updated {d.isoformat()})"
            except (ValueError, TypeError):
                break
    return base


def find_industry(path: Path | str, industry: str) -> IndustryBeta:
    """Exact (case-insensitive) industry lookup, with a helpful error otherwise."""
    table = load_industry_betas(path)
    q = industry.strip().lower()
    for name, ib in table.items():
        if name.lower() == q:
            return ib
    near = [n for n in table if q in n.lower()]
    hint = (
        f" Did you mean: {near[:5]}?"
        if near
        else " Run 'finauto betas' to list available industries."
    )
    raise DamodaranError(f"industry '{industry}' not found in {path}.{hint}")
