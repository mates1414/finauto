"""FinAuto CLI: extract / market / build / run."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from .assumptions import derive_assumptions, load_overrides
from .config import get_settings
from .engine.builder import build_workbook
from .schemas import CompanyFinancials, MarketData, ValuationInputs
from .validation.sanity import financials_gap_report, market_warnings, reconcile_financials
from .validation.sector_guard import SectorNotSupportedError, check_sector

app = typer.Typer(help="FinAuto-Valuation Engine: PDF financials -> Excel valuation model", no_args_is_help=True)
console = Console()


def _peer_list(peers: str) -> list[str]:
    return [p.strip() for p in peers.split(",") if p.strip()]


def _slug(ticker: str) -> str:
    return ticker.replace(".", "_")


def _print_warnings(warnings: list[str], title: str) -> None:
    if warnings:
        console.print(f"[yellow]{title}:[/]")
        for w in warnings:
            console.print(f"  [yellow]- {w}[/]")


@app.command()
def extract(
    pdfs: list[Path] = typer.Argument(..., exists=True, readable=True, help="Financial report PDF(s)"),
    ticker: str = typer.Option(..., "--ticker", "-t", help="Target ticker, e.g. THYAO.IS"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output financials JSON path"),
    provider: Optional[str] = typer.Option(None, "--provider", help="LLM provider: gemini | claude"),
) -> None:
    """Extract historical financials from PDF report(s) into financials.json."""
    settings = get_settings()
    if provider:
        settings.llm_provider = provider  # type: ignore[assignment]
    from .ingestion.base import get_extractor

    console.print(f"Extracting {len(pdfs)} PDF(s) for [bold]{ticker}[/] via {settings.llm_provider}...")
    fin = get_extractor(settings).extract(list(pdfs), ticker)
    out = output or Path(f"{_slug(ticker)}_financials.json")
    out.write_text(fin.model_dump_json(indent=2), encoding="utf-8")
    _print_warnings(financials_gap_report(fin), "Missing line items (blank cells in the model)")
    console.print(f"[green]Wrote {out}[/]")


@app.command()
def market(
    ticker: str = typer.Option(..., "--ticker", "-t", help="Target ticker, e.g. THYAO.IS"),
    peers: str = typer.Option(..., "--peers", "-p", help="Comma-separated peer tickers"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output market JSON path"),
    force: bool = typer.Option(False, "--force", help="Bypass the financial-sector guard"),
) -> None:
    """Fetch target + peer market snapshots from Yahoo Finance into market.json."""
    from .marketdata.yahoo import fetch_market_data

    console.print(f"Fetching market data for [bold]{ticker}[/] and peers {_peer_list(peers)}...")
    data = fetch_market_data(ticker, _peer_list(peers))
    try:
        check_sector(data.target, force=force)
    except SectorNotSupportedError as e:
        console.print(f"[red]{e}[/]")
        raise typer.Exit(code=2)
    out = output or Path(f"{_slug(ticker)}_market.json")
    out.write_text(data.model_dump_json(indent=2), encoding="utf-8")
    _print_warnings(market_warnings(data), "Market data gaps")
    console.print(f"[green]Wrote {out}[/]")


@app.command()
def build(
    financials: Path = typer.Option(..., "--financials", "-f", exists=True, help="financials.json from extract"),
    market_file: Path = typer.Option(..., "--market", "-m", exists=True, help="market.json from market"),
    assumptions_file: Optional[Path] = typer.Option(None, "--assumptions", "-a", help="assumptions.yaml overrides"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output .xlsx path"),
    locale: Optional[str] = typer.Option(None, "--locale", help="Workbook label locale: tr | en"),
    force: bool = typer.Option(False, "--force", help="Bypass the financial-sector guard"),
) -> None:
    """Build the 6-tab formula-linked Excel valuation model."""
    settings = get_settings()
    fin = CompanyFinancials.model_validate_json(financials.read_text(encoding="utf-8"))
    mkt = MarketData.model_validate_json(market_file.read_text(encoding="utf-8"))
    try:
        check_sector(mkt.target, force=force)
    except SectorNotSupportedError as e:
        console.print(f"[red]{e}[/]")
        raise typer.Exit(code=2)

    overrides = load_overrides(assumptions_file) if assumptions_file else None
    asm = derive_assumptions(fin, overrides)
    fin_clean, notes = reconcile_financials(fin)
    _print_warnings(notes, "Reconciled line items")
    _print_warnings(market_warnings(mkt), "Market data gaps")

    inputs = ValuationInputs(
        financials=fin_clean,
        market=mkt,
        assumptions=asm,
        locale=(locale or settings.locale),  # type: ignore[arg-type]
    )
    out = output or Path(f"{_slug(fin.ticker)}_valuation.xlsx")
    path = build_workbook(inputs, out)
    console.print(f"[green]Workbook written: {path}[/]")
    console.print("Open in Excel; change cells on 01_Assumptions to recompute the target price on 06_Valuation_Summary.")


@app.command()
def run(
    pdfs: list[Path] = typer.Argument(..., exists=True, readable=True, help="Financial report PDF(s)"),
    ticker: str = typer.Option(..., "--ticker", "-t"),
    peers: str = typer.Option(..., "--peers", "-p", help="Comma-separated peer tickers"),
    assumptions_file: Optional[Path] = typer.Option(None, "--assumptions", "-a"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output .xlsx path"),
    locale: Optional[str] = typer.Option(None, "--locale"),
    provider: Optional[str] = typer.Option(None, "--provider"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Full pipeline: extract -> market -> build in one shot."""
    settings = get_settings()
    if provider:
        settings.llm_provider = provider  # type: ignore[assignment]
    from .ingestion.base import get_extractor
    from .marketdata.yahoo import fetch_market_data

    console.print(f"[1/3] Extracting financials for [bold]{ticker}[/]...")
    fin = get_extractor(settings).extract(list(pdfs), ticker)
    fin_path = Path(f"{_slug(ticker)}_financials.json")
    fin_path.write_text(fin.model_dump_json(indent=2), encoding="utf-8")

    console.print("[2/3] Fetching market data...")
    mkt = fetch_market_data(ticker, _peer_list(peers))
    try:
        check_sector(mkt.target, force=force)
    except SectorNotSupportedError as e:
        console.print(f"[red]{e}[/]")
        raise typer.Exit(code=2)
    mkt_path = Path(f"{_slug(ticker)}_market.json")
    mkt_path.write_text(mkt.model_dump_json(indent=2), encoding="utf-8")

    console.print("[3/3] Building workbook...")
    overrides = load_overrides(assumptions_file) if assumptions_file else None
    fin_clean, _ = reconcile_financials(fin)
    inputs = ValuationInputs(
        financials=fin_clean,
        market=mkt,
        assumptions=derive_assumptions(fin, overrides),
        locale=(locale or settings.locale),  # type: ignore[arg-type]
    )
    out = output or Path(f"{_slug(ticker)}_valuation.xlsx")
    path = build_workbook(inputs, out)
    console.print(f"[green]Done: {path}[/] (intermediates: {fin_path}, {mkt_path})")


if __name__ == "__main__":
    app()
