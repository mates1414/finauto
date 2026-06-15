"""FinAuto CLI: extract / market / build / run / discover / report."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from .assumptions import derive_assumptions, load_overrides
from .config import get_settings
from .engine.builder import build_workbook
from .schemas import CompanyFinancials, MarketData, ValuationInputs
from .validation.sanity import (
    financials_gap_report,
    market_warnings,
    reconcile_financials,
)
from .validation.sector_guard import SectorNotSupportedError, check_sector

app = typer.Typer(
    help="FinAuto-Valuation Engine: PDF financials -> Excel valuation model",
    no_args_is_help=True,
)
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


def _print_peer_suggestions(suggestion) -> None:
    """Print resolved peers (market-cap ordered) and the dropped audit trail."""
    resolved = suggestion.resolved()
    if resolved:
        console.print("[green]Suggested peers (validated against live data):[/]")
        for c in resolved:
            cap = f"{c.market_cap:,.0f}" if c.market_cap is not None else "n/a"
            rationale = f" — {c.rationale}" if c.rationale else ""
            console.print(
                f"  [green]{c.ticker}[/] ({c.name}) · mktcap {cap}{rationale}"
            )
    else:
        console.print(
            "[yellow]No peers could be validated against live market data.[/]"
        )
    if suggestion.dropped:
        console.print("[dim]Dropped (unverified / hallucinated):[/]")
        for d in suggestion.dropped:
            console.print(f"  [dim]- {d}[/]")


def _discover_peers(settings, *, ticker, name, sector, n):
    """Run discovery + live validation; returns the PeerSuggestionSet."""
    from .marketdata.web_research import (
        PeerResearchError,
        get_peer_researcher,
        resolve_and_validate,
    )

    target = name or ticker
    provider, _model = settings.stage("discover")
    console.print(f"Researching peers for [bold]{target}[/] via {provider}...")
    try:
        suggestion = get_peer_researcher(settings).discover(target, sector=sector, n=n)
    except (PeerResearchError, ValueError) as e:
        console.print(f"[red]Peer discovery failed:[/] {e}")
        raise typer.Exit(code=1)
    return resolve_and_validate(suggestion)


def _auto_peers(settings, *, ticker, name, sector, n, assume_yes) -> list[str]:
    """Discover, validate, confirm, and return accepted peer tickers (invariant #7)."""
    suggestion = _discover_peers(settings, ticker=ticker, name=name, sector=sector, n=n)
    _print_peer_suggestions(suggestion)
    tickers = suggestion.tickers()
    if not tickers:
        console.print("[red]No validated peers to use; supply --peers manually.[/]")
        raise typer.Exit(code=1)
    if not assume_yes and not typer.confirm(
        f"Use these {len(tickers)} peers?", default=True
    ):
        console.print("[red]Aborted; supply --peers manually.[/]")
        raise typer.Exit(code=1)
    return tickers


def _fetch_kap_pdfs(ticker: str, year: int) -> list[Path]:
    """Download a year's filings from KAP and pick the Turkish annual statement."""
    from .ingestion.sources.base import SourceError, get_source
    from .ingestion.sources.kap import select_statement_pdfs

    dest = _results_dir(ticker) / "kap"
    console.print(
        f"Fetching {year} financial statements for [bold]{ticker}[/] from KAP..."
    )
    try:
        files = get_source("kap").fetch(ticker, year=year, dest_dir=dest)
    except (SourceError, ValueError) as e:
        console.print(f"[red]KAP fetch failed:[/] {e}")
        raise typer.Exit(code=1)
    pdfs = select_statement_pdfs(files)
    if not pdfs:
        console.print(
            "[red]No usable statement PDF in the KAP bundle; download manually and "
            "pass the path(s) instead.[/]"
        )
        raise typer.Exit(code=1)
    for p in pdfs:
        console.print(f"  [green]selected:[/] {p.name}")
    return pdfs


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


def _resolve_industry_beta(
    settings, beta_file: Optional[Path], industry: Optional[str]
):
    """Look up the Damodaran sector beta for --industry; warn and fall back to
    the peer-median beta if the file, library, or industry name is unavailable."""
    if not industry:
        return None
    from .marketdata.damodaran import DamodaranError, find_industry

    path = beta_file or settings.beta_reference_file
    try:
        ib = find_industry(path, industry)
    except FileNotFoundError:
        console.print(
            f"[yellow]Beta file not found: {path}; using peer-median beta.[/]"
        )
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
    pdfs: list[Path] = typer.Argument(
        ..., exists=True, readable=True, help="Financial report PDF(s)"
    ),
    ticker: str = typer.Option(
        ..., "--ticker", "-t", help="Target ticker, e.g. THYAO.IS"
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Output financials JSON path"
    ),
    provider: Optional[str] = typer.Option(
        None, "--provider", help="LLM provider: gemini | claude"
    ),
) -> None:
    """Extract historical financials from PDF report(s) into financials.json."""
    settings = get_settings()
    if provider:
        settings.llm_provider = provider  # type: ignore[assignment]

    console.print(
        f"Extracting {len(pdfs)} PDF(s) for [bold]{ticker}[/] via {settings.llm_provider}..."
    )
    fin = _run_extraction(settings, list(pdfs), ticker)
    out = output or _results_dir(ticker) / "financials.json"
    out.write_text(fin.model_dump_json(indent=2), encoding="utf-8")
    _print_warnings(
        financials_gap_report(fin), "Missing line items (blank cells in the model)"
    )
    console.print(f"[green]Wrote {out}[/]")


@app.command()
def market(
    ticker: str = typer.Option(
        ..., "--ticker", "-t", help="Target ticker, e.g. THYAO.IS"
    ),
    peers: str = typer.Option(
        ..., "--peers", "-p", help="Comma-separated peer tickers"
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Output market JSON path"
    ),
    force: bool = typer.Option(
        False, "--force", help="Bypass the financial-sector guard"
    ),
) -> None:
    """Fetch target + peer market snapshots from Yahoo Finance into market.json."""
    from .marketdata.yahoo import fetch_market_data

    console.print(
        f"Fetching market data for [bold]{ticker}[/] and peers {_peer_list(peers)}..."
    )
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
    financials: Path = typer.Option(
        ..., "--financials", "-f", exists=True, help="financials.json from extract"
    ),
    market_file: Path = typer.Option(
        ..., "--market", "-m", exists=True, help="market.json from market"
    ),
    assumptions_file: Optional[Path] = typer.Option(
        None, "--assumptions", "-a", help="assumptions.yaml overrides"
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Output .xlsx path"
    ),
    locale: Optional[str] = typer.Option(
        None, "--locale", help="Workbook label locale: tr | en"
    ),
    industry: Optional[str] = typer.Option(
        None,
        "--industry",
        help='Damodaran sector for the WACC beta, e.g. "Retail (Grocery and Food)"',
    ),
    beta_file: Optional[Path] = typer.Option(
        None,
        "--beta-file",
        help="Damodaran emerging-markets beta .xls (default: betaemerg.xls)",
    ),
    force: bool = typer.Option(
        False, "--force", help="Bypass the financial-sector guard"
    ),
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
    console.print(
        "Open in Excel; change cells on 01_Assumptions to recompute the target price on 06_Valuation_Summary."
    )


@app.command()
def run(
    pdfs: Optional[list[Path]] = typer.Argument(
        None,
        exists=True,
        readable=True,
        help="Financial report PDF(s) (omit with --from-kap)",
    ),
    ticker: str = typer.Option(..., "--ticker", "-t"),
    from_kap: bool = typer.Option(
        False,
        "--from-kap",
        help="Auto-download statements from KAP instead of passing PDFs",
    ),
    year: Optional[int] = typer.Option(
        None, "--year", help="Financial year for --from-kap, e.g. 2024"
    ),
    peers: Optional[str] = typer.Option(
        None, "--peers", "-p", help="Comma-separated peer tickers"
    ),
    auto_peers: bool = typer.Option(
        False, "--auto-peers", help="Discover + validate peers when --peers is omitted"
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Accept discovered peers without prompting"
    ),
    assumptions_file: Optional[Path] = typer.Option(None, "--assumptions", "-a"),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Output .xlsx path"
    ),
    locale: Optional[str] = typer.Option(None, "--locale"),
    industry: Optional[str] = typer.Option(
        None,
        "--industry",
        help='Damodaran sector for the WACC beta, e.g. "Retail (Grocery and Food)"',
    ),
    beta_file: Optional[Path] = typer.Option(
        None,
        "--beta-file",
        help="Damodaran emerging-markets beta .xls (default: betaemerg.xls)",
    ),
    provider: Optional[str] = typer.Option(None, "--provider"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Full pipeline: extract -> market -> build in one shot."""
    settings = get_settings()
    if provider:
        settings.llm_provider = provider  # type: ignore[assignment]
    if from_kap:
        if year is None:
            console.print("[red]--from-kap requires --year, e.g. --year 2024.[/]")
            raise typer.Exit(code=2)
        pdfs = _fetch_kap_pdfs(ticker, year)
    elif not pdfs:
        console.print("[red]Provide PDF path(s), or use --from-kap --year YYYY.[/]")
        raise typer.Exit(code=2)
    if not peers and not auto_peers:
        console.print("[red]Provide --peers, or pass --auto-peers to discover them.[/]")
        raise typer.Exit(code=2)
    from .marketdata.yahoo import fetch_market_data

    console.print(f"[1/3] Extracting financials for [bold]{ticker}[/]...")
    fin = _run_extraction(settings, list(pdfs), ticker)
    rdir = _results_dir(ticker)
    fin_path = rdir / "financials.json"
    fin_path.write_text(fin.model_dump_json(indent=2), encoding="utf-8")

    if peers:
        peer_tickers = _peer_list(peers)
    else:
        peer_tickers = _auto_peers(
            settings,
            ticker=ticker,
            name=fin.name,
            sector=fin.sector_hint,
            n=5,
            assume_yes=yes,
        )
        (rdir / "peers.json").write_text(
            json.dumps(peer_tickers, indent=2), encoding="utf-8"
        )

    console.print("[2/3] Fetching market data...")
    mkt = fetch_market_data(ticker, peer_tickers)
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
def discover(
    ticker: str = typer.Option(
        ..., "--ticker", "-t", help="Target ticker, e.g. BIMAS.IS"
    ),
    name: Optional[str] = typer.Option(
        None, "--name", help="Company name (improves the search)"
    ),
    sector: Optional[str] = typer.Option(
        None, "--sector", help="Sector hint to narrow the search"
    ),
    count: int = typer.Option(5, "--count", "-n", help="Number of peers to propose"),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Output peers.json path"
    ),
    provider: Optional[str] = typer.Option(
        None, "--provider", help="Discovery provider: gemini | claude"
    ),
) -> None:
    """Discover + validate comparable peers for a target (writes peers.json)."""
    settings = get_settings()
    if provider:
        settings.discover_provider = provider  # type: ignore[assignment]
    suggestion = _discover_peers(
        settings, ticker=ticker, name=name, sector=sector, n=count
    )
    _print_peer_suggestions(suggestion)
    out = output or _results_dir(ticker) / "peers.json"
    out.write_text(suggestion.model_dump_json(indent=2), encoding="utf-8")
    console.print(
        f"[green]Wrote {out}[/] ({len(suggestion.tickers())} validated, "
        f"{len(suggestion.dropped)} dropped)"
    )


@app.command()
def report(
    workbook: Path = typer.Argument(
        ..., exists=True, readable=True, help="Edited valuation .xlsx"
    ),
    financials: Optional[Path] = typer.Option(
        None, "--financials", "-f", help="Original financials.json (for the edit diff)"
    ),
    market_file: Optional[Path] = typer.Option(
        None, "--market", "-m", help="market.json (for peer names)"
    ),
    output: Optional[Path] = typer.Option(
        None, "--out", "-o", help="Output markdown path"
    ),
    provider: Optional[str] = typer.Option(
        None, "--provider", help="Report provider: claude | gemini"
    ),
    no_stream: bool = typer.Option(
        False, "--no-stream", help="Disable streaming generation"
    ),
    skip_recalc: bool = typer.Option(
        False, "--skip-recalc", help="Trust cached values already in the workbook"
    ),
) -> None:
    """Generate a grounded strategic report from a user-corrected workbook."""
    settings = get_settings()
    if provider:
        settings.report_provider = provider  # type: ignore[assignment]
    from .engine.readback import RecalcError, read_inputs, recalc
    from .report import build_context, generate, ungrounded_figures
    from .schemas import CompanyFinancials, MarketData

    # Default the intermediates to the workbook's own results folder.
    fin_path = financials or (workbook.parent / "financials.json")
    mkt_path = market_file or (workbook.parent / "market.json")
    original = (
        CompanyFinancials.model_validate_json(fin_path.read_text("utf-8"))
        if fin_path.exists()
        else None
    )
    market = (
        MarketData.model_validate_json(mkt_path.read_text("utf-8"))
        if mkt_path.exists()
        else None
    )
    ticker = original.ticker if original else ""
    name = original.name if original else None

    if skip_recalc:
        recalced = workbook
    else:
        console.print("Recalculating workbook (LibreOffice / formulas)...")
        try:
            recalced = recalc(workbook)
        except RecalcError as e:
            console.print(f"[red]{e}[/]")
            raise typer.Exit(code=1)

    fin_edited, _asm, computed = read_inputs(recalced, ticker=ticker, name=name)
    ctx = build_context(fin_edited, computed, original=original, market=market)

    console.print(f"Generating report via {settings.stage('report')[0]}...")
    rpt = generate(ctx, settings, stream=not no_stream)

    ungrounded = ungrounded_figures(rpt.markdown, ctx)
    _print_warnings(
        ungrounded,
        "Ungrounded figures in the narrative (verify before relying on them)",
    )

    out = output or _results_dir(ticker or "report") / "report.md"
    out.write_text(rpt.markdown, encoding="utf-8")
    console.print(rpt.markdown)
    console.print(f"[green]Wrote {out}[/]")


@app.command()
def fetch(
    ticker: str = typer.Option(
        ..., "--ticker", "-t", help="Target ticker, e.g. THYAO.IS"
    ),
    year: int = typer.Option(
        ..., "--year", help="Financial year to download, e.g. 2024"
    ),
    source: str = typer.Option("kap", "--source", help="Data source: kap"),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Destination folder (default: results/<TICKER>/<source>)",
    ),
) -> None:
    """Download financial-statement files for a ticker from a public source (KAP)."""
    from .ingestion.sources.base import SourceError, get_source

    dest = output or _results_dir(ticker) / source
    console.print(
        f"Fetching {year} financial statements for [bold]{ticker}[/] from {source}..."
    )
    try:
        paths = get_source(source).fetch(ticker, year=year, dest_dir=dest)
    except (SourceError, ValueError) as e:
        console.print(f"[red]Fetch failed:[/] {e}")
        raise typer.Exit(code=1)
    for p in paths:
        console.print(f"  [green]{p}[/]")
    console.print(f"[green]Wrote {len(paths)} file(s) to {dest}[/]")
    console.print(
        "[dim]Note: post-2022 BIST statements are TMS-29/IAS-29 inflation-restated.[/]"
    )


@app.command()
def betas(
    query: Optional[str] = typer.Argument(
        None, help="Case-insensitive substring to filter industries"
    ),
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
