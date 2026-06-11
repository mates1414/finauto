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

RESULTS_DIR = Path("results")


def _peer_list(peers: str) -> list[str]:
    return [p.strip() for p in peers.split(",") if p.strip()]


def _slug(ticker: str) -> str:
    return ticker.replace(".", "_")


def _results_dir(ticker: str) -> Path:
    """Per-company output folder: results/<TICKER>/ (created on demand)."""
    d = RESULTS_DIR / _slug(ticker)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _print_warnings(warnings: list[str], title: str) -> None:
    if warnings:
        console.print(f"[yellow]{title}:[/]")
        for w in warnings:
            console.print(f"  [yellow]- {w}[/]")


def _run_extraction(settings, pdfs: list[Path], ticker: str):
    """Extract financials, turning expected failures into clean CLI errors."""
    from .ingestion.base import ExtractionError, get_extractor

    try:
        fin = get_extractor(settings).extract(list(pdfs), ticker)
    except (ExtractionError, ValueError) as e:
        console.print(f"[red]Extraction failed:[/] {e}")
        raise typer.Exit(code=1)
    # Collapse any same-year duplicates from overlapping reports into one column.
    return fin.with_deduped_periods()


def _resolve_industry_beta(settings, beta_file: Optional[Path], industry: Optional[str]):
    """Look up the Damodaran sector beta for --industry; warn and fall back to
    the peer-median beta if the file, library, or industry name is unavailable."""
    if not industry:
        return None
    from .marketdata.damodaran import DamodaranError, find_industry

    path = beta_file or settings.beta_reference_file
    try:
        ib = find_industry(path, industry)
    except FileNotFoundError:
        console.print(f"[yellow]Beta file not found: {path}; using peer-median beta.[/]")
        return None
    except ImportError as e:
        console.print(f"[yellow]{e}; using peer-median beta.[/]")
        return None
    except DamodaranError as e:
        console.print(f"[yellow]{e} Using peer-median beta.[/]")
        return None
    console.print(
        f"[green]WACC beta from Damodaran:[/] {ib.industry} "
        f"-> unlevered (cash-adj) {ib.chosen_unlevered():.3f}"
    )
    return ib


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

    console.print(f"Extracting {len(pdfs)} PDF(s) for [bold]{ticker}[/] via {settings.llm_provider}...")
    fin = _run_extraction(settings, list(pdfs), ticker)
    out = output or _results_dir(ticker) / "financials.json"
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
    out = output or _results_dir(ticker) / "market.json"
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
    industry: Optional[str] = typer.Option(
        None, "--industry", help='Damodaran sector for the WACC beta, e.g. "Retail (Grocery and Food)"'
    ),
    beta_file: Optional[Path] = typer.Option(
        None, "--beta-file", help="Damodaran emerging-markets beta .xls (default: betaemerg.xls)"
    ),
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
        industry_beta=_resolve_industry_beta(settings, beta_file, industry),
    )
    out = output or _results_dir(fin.ticker) / f"{_slug(fin.ticker)}_valuation.xlsx"
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
    industry: Optional[str] = typer.Option(
        None, "--industry", help='Damodaran sector for the WACC beta, e.g. "Retail (Grocery and Food)"'
    ),
    beta_file: Optional[Path] = typer.Option(
        None, "--beta-file", help="Damodaran emerging-markets beta .xls (default: betaemerg.xls)"
    ),
    provider: Optional[str] = typer.Option(None, "--provider"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Full pipeline: extract -> market -> build in one shot."""
    settings = get_settings()
    if provider:
        settings.llm_provider = provider  # type: ignore[assignment]
    from .marketdata.yahoo import fetch_market_data

    console.print(f"[1/3] Extracting financials for [bold]{ticker}[/]...")
    fin = _run_extraction(settings, list(pdfs), ticker)
    rdir = _results_dir(ticker)
    fin_path = rdir / "financials.json"
    fin_path.write_text(fin.model_dump_json(indent=2), encoding="utf-8")

    console.print("[2/3] Fetching market data...")
    mkt = fetch_market_data(ticker, _peer_list(peers))
    try:
        check_sector(mkt.target, force=force)
    except SectorNotSupportedError as e:
        console.print(f"[red]{e}[/]")
        raise typer.Exit(code=2)
    mkt_path = rdir / "market.json"
    mkt_path.write_text(mkt.model_dump_json(indent=2), encoding="utf-8")

    console.print("[3/3] Building workbook...")
    overrides = load_overrides(assumptions_file) if assumptions_file else None
    fin_clean, _ = reconcile_financials(fin)
    inputs = ValuationInputs(
        financials=fin_clean,
        market=mkt,
        assumptions=derive_assumptions(fin, overrides),
        locale=(locale or settings.locale),  # type: ignore[arg-type]
        industry_beta=_resolve_industry_beta(settings, beta_file, industry),
    )
    out = output or rdir / f"{_slug(ticker)}_valuation.xlsx"
    path = build_workbook(inputs, out)
    console.print(f"[green]Done: {path}[/] (intermediates: {fin_path}, {mkt_path})")


@app.command()
def betas(
    query: Optional[str] = typer.Argument(None, help="Case-insensitive substring to filter industries"),
    beta_file: Optional[Path] = typer.Option(
        None, "--beta-file", help="Damodaran beta .xls (default: betaemerg.xls)"
    ),
) -> None:
    """List industries in the Damodaran emerging-markets beta reference file."""
    settings = get_settings()
    path = beta_file or settings.beta_reference_file
    from .marketdata.damodaran import load_industry_betas

    try:
        table = load_industry_betas(path)
    except (FileNotFoundError, ImportError, ValueError) as e:
        console.print(f"[red]{e}[/]")
        raise typer.Exit(code=1)

    def fmt(v: Optional[float]) -> str:
        return f"{v:.3f}" if v is not None else "  -  "

    shown = 0
    for name in sorted(table):
        if query and query.lower() not in name.lower():
            continue
        ib = table[name]
        console.print(
            f"{name}  [dim](unlev {fmt(ib.unlevered_beta)}, "
            f"cash-adj {fmt(ib.unlevered_beta_cash_adj)})[/]"
        )
        shown += 1
    console.print(f"[dim]{shown} industries[/]")


if __name__ == "__main__":
    app()
