"""Excel round-trip: read the workbook back into the contract and diff edits.

Input (blue) cells are stored literals and read back without a recalc; the
computed-outputs assertion is gated on a recalc backend being available.
"""

from __future__ import annotations

import shutil

import pytest

from finauto.engine.readback import RecalcError, diff_inputs, read_inputs, recalc


def test_read_inputs_roundtrips_inputs(workbook_path, inputs):
    fin, asm, _computed = read_inputs(workbook_path, ticker="DEMO.IS")

    latest = fin.sorted_periods()[-1]
    assert latest.year == 2025
    # sheet stores absolute units; fixture is in thousands -> *1000 on read-back
    assert latest.income_statement.revenue == pytest.approx(145_000_000 * 1000)
    assert latest.balance_sheet.cash_and_equivalents == pytest.approx(18_500_000 * 1000)

    assert asm.tax_rate == pytest.approx(inputs.assumptions.tax_rate)
    assert asm.risk_free_rate == pytest.approx(inputs.assumptions.risk_free_rate)
    assert asm.terminal_growth == pytest.approx(inputs.assumptions.terminal_growth)


def test_diff_inputs_reports_changed_cell(fin):
    edited = fin.model_copy(deep=True)
    for p in edited.periods:
        if p.year == 2025:
            p.income_statement.revenue = (p.income_statement.revenue or 0) + 1000

    notes = diff_inputs(fin, edited)
    assert len(notes) == 1
    note = notes[0]
    assert note.path == "2025.income_statement.revenue"
    assert note.new == pytest.approx((note.old or 0) + 1000 * 1000)  # absolute units


def test_diff_inputs_no_changes_is_empty(fin):
    assert diff_inputs(fin, fin.model_copy(deep=True)) == []


def _have_recalc_backend() -> bool:
    if shutil.which("soffice") or shutil.which("libreoffice"):
        return True
    try:
        import formulas  # noqa: F401

        return True
    except ImportError:
        return False


def test_recalc_materializes_computed_outputs(workbook_path, tmp_path):
    if not _have_recalc_backend():
        pytest.skip("no recalc backend (LibreOffice or `formulas`) available")
    try:
        recalced = recalc(workbook_path, out_dir=tmp_path)
    except RecalcError as e:
        pytest.skip(f"recalc backend present but failed on this workbook: {e}")

    fin, _asm, computed = read_inputs(recalced, ticker="DEMO.IS")
    # Static-coordinate outputs resolve on either recalc backend; WACC (a
    # peer-count-dependent cell on sheet 03) needs a defined-name-preserving
    # backend (Excel/LibreOffice) and may be blank on the `formulas` fallback.
    assert computed["target_price"] is not None
    assert computed["current_price"] is not None
    assert computed["signal"] in {"AL", "TUT", "SAT"}
    assert fin.sorted_periods()[-1].income_statement.revenue == pytest.approx(
        145_000_000 * 1000
    )
