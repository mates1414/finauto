"""yfinance snapshots for the target and peer tickers.

Works for any exchange; the only ticker-specific logic is picking a benchmark
index for the beta-regression fallback when Yahoo does not publish a beta.
"""

from __future__ import annotations

import math

import yfinance as yf

from ..schemas import MarketData, TickerSnapshot

# benchmark index per ticker suffix; default is S&P 500
BENCHMARKS: dict[str, str] = {
    ".IS": "^XU100",
    ".L": "^FTSE",
    ".DE": "^GDAXI",
    ".PA": "^FCHI",
    ".AS": "^AEX",
    ".MC": "^IBEX",
    ".MI": "FTSEMIB.MI",
    ".SW": "^SSMI",
    ".WA": "WIG20.WA",
}
DEFAULT_BENCHMARK = "^GSPC"


def benchmark_for(ticker: str) -> str:
    if "." in ticker:
        suffix = "." + ticker.rsplit(".", 1)[1]
        return BENCHMARKS.get(suffix.upper(), DEFAULT_BENCHMARK)
    return DEFAULT_BENCHMARK


def _num(info: dict, *keys: str) -> float | None:
    for k in keys:
        v = info.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
            return float(v)
    return None


def regression_beta(ticker: str, period: str = "2y") -> float | None:
    """Weekly-returns beta vs the suffix-matched benchmark index."""
    bench = benchmark_for(ticker)
    try:
        data = yf.download(
            [ticker, bench], period=period, interval="1wk",
            progress=False, auto_adjust=True,
        )["Close"]
    except Exception:
        return None
    if data is None or ticker not in data or bench not in data:
        return None
    rets = data[[ticker, bench]].pct_change().dropna()
    if len(rets) < 30:
        return None
    var = rets[bench].var()
    if not var:
        return None
    return float(rets[ticker].cov(rets[bench]) / var)


def snapshot(ticker: str, beta_fallback: bool = True) -> TickerSnapshot:
    info = yf.Ticker(ticker).info or {}
    price = _num(info, "currentPrice", "regularMarketPrice", "previousClose")
    shares = _num(info, "sharesOutstanding", "impliedSharesOutstanding")
    market_cap = _num(info, "marketCap")
    if market_cap is None and price is not None and shares is not None:
        market_cap = price * shares
    beta = _num(info, "beta")
    if beta is None and beta_fallback:
        beta = regression_beta(ticker)
    return TickerSnapshot(
        ticker=ticker,
        name=info.get("longName") or info.get("shortName"),
        currency=info.get("currency"),
        price=price,
        shares_outstanding=shares,
        market_cap=market_cap,
        beta=beta,
        total_debt=_num(info, "totalDebt"),
        cash=_num(info, "totalCash"),
        ebitda=_num(info, "ebitda"),
        revenue=_num(info, "totalRevenue"),
        net_income=_num(info, "netIncomeToCommon"),
        sector=info.get("sector"),
        industry=info.get("industry"),
    )


def fetch_market_data(target: str, peers: list[str]) -> MarketData:
    return MarketData(
        target=snapshot(target),
        peers=[snapshot(p) for p in peers],
    )
