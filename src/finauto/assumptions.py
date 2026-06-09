"""Derive sensible default Assumptions from historicals, then apply overrides."""

from __future__ import annotations

import statistics
from pathlib import Path

import yaml

from .schemas import Assumptions, CompanyFinancials, FiscalYearData


def _median(values: list[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return statistics.median(vals) if vals else None


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _effective_ebit(p: FiscalYearData) -> float | None:
    inc = p.income_statement
    if inc.ebit is not None:
        return inc.ebit
    da = inc.depreciation_amortization or p.cash_flow.depreciation_amortization
    if inc.ebitda is not None and da is not None:
        return inc.ebitda - da
    return None


def derive_assumptions(financials: CompanyFinancials, overrides: dict | None = None) -> Assumptions:
    """Defaults from historical medians; explicit overrides always win."""
    fin = financials.normalized()
    periods = fin.sorted_periods()

    growths: list[float] = []
    for prev, cur in zip(periods, periods[1:]):
        a, b = prev.income_statement.revenue, cur.income_statement.revenue
        if a and b is not None:
            growths.append(b / a - 1)

    margins, capex_pcts, da_pcts = [], [], []
    for p in periods:
        rev = p.income_statement.revenue
        if not rev:
            continue
        ebit = _effective_ebit(p)
        if ebit is not None:
            margins.append(ebit / rev)
        if p.cash_flow.capex is not None:
            capex_pcts.append(abs(p.cash_flow.capex) / rev)
        da = p.income_statement.depreciation_amortization or p.cash_flow.depreciation_amortization
        if da is not None:
            da_pcts.append(abs(da) / rev)

    derived: dict[str, float] = {}
    g1 = _median(growths)
    if g1 is not None:
        derived["growth_stage1"] = _clamp(g1, -0.05, 0.60)
    margin = _median(margins)
    if margin is not None:
        derived["ebit_margin"] = _clamp(margin, -0.10, 0.60)
    capex = _median(capex_pcts)
    if capex is not None:
        derived["capex_pct_sales"] = _clamp(capex, 0.0, 0.40)
    da = _median(da_pcts)
    if da is not None:
        derived["da_pct_sales"] = _clamp(da, 0.0, 0.30)

    base = Assumptions()
    if "growth_stage1" in derived and "growth_stage2" not in derived:
        # fade stage-1 growth halfway toward terminal growth by default
        derived["growth_stage2"] = (derived["growth_stage1"] + base.terminal_growth) / 2

    merged = {**derived, **{k: v for k, v in (overrides or {}).items() if v is not None}}
    return Assumptions(**merged)


def load_overrides(path: Path) -> dict:
    """Read an assumptions.yaml whose keys match Assumptions field names."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a mapping of assumption overrides")
    unknown = set(data) - set(Assumptions.model_fields)
    if unknown:
        raise ValueError(f"{path}: unknown assumption keys: {sorted(unknown)}")
    return data
