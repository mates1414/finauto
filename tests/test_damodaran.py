from __future__ import annotations

from pathlib import Path

import pytest

from finauto.marketdata.damodaran import (
    DamodaranError,
    find_industry,
    parse_industry_rows,
)

# A few rows mimicking the "Industry Averages" sheet layout (header + data + blank).
ROWS = [
    ["Date updated:", 46027.0],
    ["What is this data?", "Beta, Unlevered beta and other risk measures"],
    [
        "Industry Name", "Number of firms", "Beta ", "D/E Ratio", "Effective Tax rate",
        "Unlevered beta", "Cash/Firm value", "Unlevered beta corrected for cash",
    ],
    ["Retail (Grocery and Food)", 97, 1.014, 0.378, 0.175, 0.7894, 0.078, 0.8562],
    ["Food Processing", 1030, 0.720, 0.380, 0.164, 0.5602, 0.079, 0.6083],
    ["", "", "", "", "", "", "", ""],  # trailing blank row is ignored
]

BETA_FILE = Path(__file__).resolve().parents[1] / "betaemerg.xls"


def test_parse_industry_rows_maps_columns():
    table = parse_industry_rows(ROWS, source="Damodaran EM (test)")
    assert set(table) == {"Retail (Grocery and Food)", "Food Processing"}
    ib = table["Retail (Grocery and Food)"]
    assert ib.unlevered_beta == pytest.approx(0.7894)
    assert ib.unlevered_beta_cash_adj == pytest.approx(0.8562)
    assert ib.de_ratio == pytest.approx(0.378)
    # cash-adjusted is the default for relevering; standard available on request
    assert ib.chosen_unlevered() == pytest.approx(0.8562)
    assert ib.chosen_unlevered(cash_adjusted=False) == pytest.approx(0.7894)
    assert ib.source == "Damodaran EM (test)"


def test_parse_requires_header_row():
    with pytest.raises(DamodaranError):
        parse_industry_rows([["foo", "bar"], ["x", 1, 2]])


@pytest.mark.skipif(not BETA_FILE.exists(), reason="betaemerg.xls not present")
def test_find_industry_real_file_is_case_insensitive():
    ib = find_industry(BETA_FILE, "retail (grocery and food)")
    assert ib.unlevered_beta_cash_adj == pytest.approx(0.8562, abs=0.02)
    with pytest.raises(DamodaranError):
        find_industry(BETA_FILE, "NoSuchSector")
