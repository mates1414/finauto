import pytest

from finauto.assumptions import derive_assumptions, load_overrides


def test_derived_growth_is_median_of_history(fin):
    asm = derive_assumptions(fin)
    # yearly growth: 40.0%, 34.5%, 28.3% -> median ~34.5%
    assert asm.growth_stage1 == pytest.approx(0.3452, abs=0.001)
    # stage 2 fades halfway toward terminal growth
    assert asm.growth_stage2 == pytest.approx((asm.growth_stage1 + 0.03) / 2, abs=1e-9)


def test_derived_margins_and_ratios(fin):
    asm = derive_assumptions(fin)
    assert 0.09 < asm.ebit_margin < 0.13
    assert 0.06 < asm.capex_pct_sales < 0.08
    assert 0.03 < asm.da_pct_sales < 0.06


def test_overrides_win(fin):
    asm = derive_assumptions(fin, {"tax_rate": 0.30, "growth_stage1": 0.10})
    assert asm.tax_rate == 0.30
    assert asm.growth_stage1 == 0.10


def test_load_overrides_rejects_unknown_keys(tmp_path):
    p = tmp_path / "assumptions.yaml"
    p.write_text("not_a_field: 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unknown assumption keys"):
        load_overrides(p)


def test_load_overrides_roundtrip(tmp_path, fin):
    p = tmp_path / "assumptions.yaml"
    p.write_text("risk_free_rate: 0.35\nterminal_growth: 0.025\n", encoding="utf-8")
    asm = derive_assumptions(fin, load_overrides(p))
    assert asm.risk_free_rate == 0.35
    assert asm.terminal_growth == 0.025
