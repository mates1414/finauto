import pytest

from finauto.schemas import (
    CompanyFinancials,
    FiscalYearData,
    IncomeStatement,
    TickerSnapshot,
)
from finauto.validation.sanity import reconcile_financials, snapshot_warnings
from finauto.validation.sector_guard import SectorNotSupportedError, check_sector


def _fin(**inc) -> CompanyFinancials:
    return CompanyFinancials(
        ticker="X",
        units="units",
        periods=[FiscalYearData(year=2025, income_statement=IncomeStatement(**inc))],
    )


def test_reconcile_cogs_from_gross_profit():
    fin = _fin(revenue=100.0, gross_profit=40.0)
    out, notes = reconcile_financials(fin)
    assert out.latest.income_statement.cogs == 60.0
    assert any("COGS" in n for n in notes)


def test_reconcile_ebitda_from_ebit_plus_da():
    fin = _fin(ebit=50.0, depreciation_amortization=10.0)
    out, _ = reconcile_financials(fin)
    assert out.latest.income_statement.ebitda == 60.0


def test_reconcile_fixture_2022_ebitda(fin):
    out, _ = reconcile_financials(fin)
    y2022 = out.sorted_periods()[0]
    assert y2022.income_statement.ebitda == 8_500_000  # ebit 5.5m + da 3.0m


def test_negative_net_debt_warning():
    snap = TickerSnapshot(ticker="X", total_debt=5.0, cash=50.0)
    warns = snapshot_warnings(snap)
    assert any("negative net debt" in w for w in warns)


def test_sector_guard_blocks_bank():
    snap = TickerSnapshot(ticker="GARAN.IS", sector="Financial Services", industry="Banks - Regional")
    with pytest.raises(SectorNotSupportedError):
        check_sector(snap)


def test_sector_guard_force_bypasses():
    snap = TickerSnapshot(ticker="GARAN.IS", sector="Financial Services", industry="Banks")
    check_sector(snap, force=True)  # no raise


def test_sector_guard_allows_industrials(market):
    check_sector(market.target)  # no raise
