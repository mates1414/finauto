"""Data hygiene: reconcile derivable statement lines and report data gaps.

The Excel layer keeps its own guards (MAX(0,debt) clamps, IFERROR on every
division); this module fixes what can be fixed before anything is written.
"""

from __future__ import annotations

from .. import schemas
from ..schemas import CompanyFinancials, MarketData, TickerSnapshot


def reconcile_financials(fin: CompanyFinancials) -> tuple[CompanyFinancials, list[str]]:
    """Fill statement lines that are arithmetically derivable from the others.

    Returns the reconciled copy plus human-readable notes of what was filled.
    The sheet engine assumes: Gross Profit = Revenue - COGS, EBIT = EBITDA - D&A.
    """
    out = fin.model_copy(deep=True)
    notes: list[str] = []
    for p in out.periods:
        inc, cf = p.income_statement, p.cash_flow
        if inc.depreciation_amortization is None and cf.depreciation_amortization is not None:
            inc.depreciation_amortization = cf.depreciation_amortization
            notes.append(f"{p.year}: D&A taken from cash flow statement")
        if inc.cogs is None and inc.revenue is not None and inc.gross_profit is not None:
            inc.cogs = inc.revenue - inc.gross_profit
            notes.append(f"{p.year}: COGS derived from Revenue - Gross Profit")
        if inc.gross_profit is None and inc.revenue is not None and inc.cogs is not None:
            inc.gross_profit = inc.revenue - inc.cogs
        if inc.ebitda is None:
            if inc.ebit is not None and inc.depreciation_amortization is not None:
                inc.ebitda = inc.ebit + inc.depreciation_amortization
                notes.append(f"{p.year}: EBITDA derived from EBIT + D&A")
            elif inc.gross_profit is not None and inc.sga is not None:
                inc.ebitda = inc.gross_profit - inc.sga
                notes.append(f"{p.year}: EBITDA approximated as Gross Profit - SG&A")
        if inc.ebit is None and inc.ebitda is not None and inc.depreciation_amortization is not None:
            inc.ebit = inc.ebitda - inc.depreciation_amortization
    return out, notes


def financials_gap_report(fin: CompanyFinancials) -> list[str]:
    gaps: list[str] = []
    for p in fin.sorted_periods():
        for section in (p.income_statement, p.balance_sheet, p.cash_flow):
            for fname in type(section).model_fields:
                if getattr(section, fname) is None:
                    gaps.append(f"{p.year}: {fname}")
    return gaps


def snapshot_warnings(snap: TickerSnapshot) -> list[str]:
    warns = [f"{snap.ticker}: missing {f}" for f in snap.missing_fields()]
    if snap.total_debt is not None and snap.cash is not None and snap.total_debt < snap.cash:
        warns.append(
            f"{snap.ticker}: negative net debt (cash exceeds gross debt); "
            "beta unlevering clamps debt at 0"
        )
    return warns


def market_warnings(market: MarketData) -> list[str]:
    warns = snapshot_warnings(market.target)
    for peer in market.peers:
        warns.extend(snapshot_warnings(peer))
    return warns
