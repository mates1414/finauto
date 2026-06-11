from finauto.schemas import (
    BalanceSheet,
    CompanyFinancials,
    FiscalYearData,
    IncomeStatement,
    TickerSnapshot,
)


def test_normalized_converts_thousands_to_units(fin):
    norm = fin.normalized()
    assert norm.units == "units"
    assert norm.latest.income_statement.revenue == 145_000_000 * 1000
    assert norm.latest.balance_sheet.cash_and_equivalents == 18_500_000 * 1000
    # original untouched
    assert fin.latest.income_statement.revenue == 145_000_000


def test_sorted_periods(fin):
    years = [p.year for p in fin.sorted_periods()]
    assert years == sorted(years)
    assert fin.latest.year == 2025


def test_missing_fields():
    snap = TickerSnapshot(ticker="X", price=10.0)
    missing = snap.missing_fields()
    assert "beta" in missing and "price" not in missing


def test_deduped_periods_merges_same_year_and_preserves_distinct():
    # Same year 2024 split across two overlapping reports, complementary blanks
    a = FiscalYearData(
        year=2024,
        income_statement=IncomeStatement(revenue=100.0, ebitda=None),
        balance_sheet=BalanceSheet(cash_and_equivalents=None),
    )
    b = FiscalYearData(
        year=2024,
        income_statement=IncomeStatement(revenue=999.0, ebitda=30.0),  # first-seen wins for revenue
        balance_sheet=BalanceSheet(cash_and_equivalents=15.0),
    )
    c = FiscalYearData(year=2023, income_statement=IncomeStatement(revenue=80.0))
    fin = CompanyFinancials(ticker="X", periods=[a, b, c])

    deduped = fin.deduped_periods()
    assert [p.year for p in deduped] == [2023, 2024]  # one entry per year, sorted
    merged = deduped[1]
    assert merged.income_statement.revenue == 100.0  # base (first-seen) wins
    assert merged.income_statement.ebitda == 30.0  # blank filled from later copy
    assert merged.balance_sheet.cash_and_equivalents == 15.0
    # original is untouched (returns a new list/copies)
    assert len(fin.periods) == 3
