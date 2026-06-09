"""MVP sector isolation: financial institutions value operations fundamentally
differently (no meaningful FCFF/EV), so they are rejected up front."""

from __future__ import annotations

from ..schemas import TickerSnapshot

BLOCKED_PATTERNS = (
    "bank",
    "insurance",
    "reit",
    "real estate investment",
    "financial services",
    "capital markets",
    "asset management",
    "mortgage",
    "credit services",
)


class SectorNotSupportedError(Exception):
    def __init__(self, ticker: str, sector: str | None, industry: str | None):
        self.ticker, self.sector, self.industry = ticker, sector, industry
        super().__init__(
            f"{ticker}: sector '{sector}' / industry '{industry}' is a financial "
            "institution; the FCFF-based MVP does not support banks, insurers or "
            "REITs. Use --force to bypass at your own risk."
        )


def check_sector(snapshot: TickerSnapshot, force: bool = False) -> None:
    if force:
        return
    haystack = f"{snapshot.sector or ''} {snapshot.industry or ''}".lower()
    if any(p in haystack for p in BLOCKED_PATTERNS):
        raise SectorNotSupportedError(snapshot.ticker, snapshot.sector, snapshot.industry)
