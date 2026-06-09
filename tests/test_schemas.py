from finauto.schemas import TickerSnapshot


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
