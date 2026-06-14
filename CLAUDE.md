# finauto — App Guide (extends the workspace `../CLAUDE.md`)

This file **adds finauto-specific** guidance. The shared coding conventions and finance
invariants live in the workspace `../CLAUDE.md` (Claude Code merges parent → child). Deep
detail lives in [README.md](README.md) and the architecture doc [plan.md](plan.md) — read
those before non-trivial changes; don't duplicate them here.

## What finauto is
PDF financials → LLM extraction → yfinance market data → a 6-tab, fully formula-linked Excel
valuation model (10-yr DCF + peer multiples) with an AL/TUT/SAT signal. Own git repo; `.venv`
lives at `.venv/`.

## The contract: decoupled 3-stage pipeline (do not couple the stages)
```
finauto extract  : PDF(s) ──LLM──▶ *_financials.json   (pydantic-validated)
finauto market   : tickers ──yfinance──▶ *_market.json (target + peers)
finauto build    : financials.json + market.json ──▶ model.xlsx
finauto run      : all three chained (──auto-peers to discover peers)
finauto discover : target ──LLM+web search──▶ peers.json (validated vs live data)
finauto report   : edited model.xlsx ──recalc+read-back+LLM──▶ grounded report.md
```
The **JSON intermediates are the public contract** (they become API/DB payloads in Phase 3).
The Excel engine must never import an LLM SDK or hit the network — keep `engine/` pure
(the one edge in `engine/readback.recalc` shells out to LibreOffice/`formulas`, not an SDK).

## Module map (`src/finauto/`)
- `cli.py` — Typer app (`extract`/`market`/`build`/`run`); no business logic here.
- `config.py` — pydantic-settings (provider, locale, defaults). `schemas.py` — all contracts.
- `labels.py` — `LABELS = {"tr": …, "en": …}`; row/header labels localize, sheet/function names don't.
- `ingestion/` — `base.py` (Extractor protocol + factory; routes via `Settings.stage("extract")`),
  `gemini.py`, `claude.py` (native PDF), `openai_compat.py` (OpenAI-compatible: DeepSeek/OpenRouter/…,
  **text-only** — uses `pdf_loader.load_pdf_text`, cheaper but lower table fidelity), `prompts.py`,
  `pdf_loader.py`. **Add a provider by implementing the protocol**, never by branching in callers.
- `marketdata/yahoo.py` — `snapshot(ticker)`; weekly-returns beta regression fallback (`^XU100` for `.IS`).
- `marketdata/web_research.py` — Phase 3 peer discovery: `PeerResearcher` protocol + factory
  (Gemini grounding / Claude `web_search`); `resolve_and_validate` is the hallucination filter
  (drops any peer that fails a live `yahoo.snapshot`).
- `validation/` — `sector_guard.py` (banks/insurers/REITs → error unless `--force`), `sanity.py`.
- `engine/` — `builder.py`, `formulas.py` (ref helpers + `iferror()`), `styles.py`, `sheets/` (s01–s06).
- `engine/readback.py` — Phase 3 Excel round-trip: `recalc` (LibreOffice/`formulas`), `read_inputs`
  (openpyxl `data_only`, by the symbolic row maps), `diff_inputs`. Workbook is sheet-protected with
  only the blue input cells unlocked.
- `report/` — Phase 3 strategic report: `ReportWriter` protocol + factory, grounded-context assembly,
  and `ungrounded_figures` (the no-fabrication check, invariant #8).
- `llm/batch.py` — Phase 3 cost control: provider-aware batch submission (Anthropic Batch API).
  Per-stage provider/model routing lives in `config.Settings.stage()`.

## finauto-specific invariants (on top of the workspace ones)
- **Hardcoded raw numbers ONLY on sheets 01/02/03.** Sheets 04 (DCF) and 05 (multiples) are
  **formula-only** — zero literal numbers. See the 6-sheet blueprint in [plan.md](plan.md).
- Net debt (incl. leases) and the net-debt bridge must be identical on sheet 04 and sheet 05.
- Excel **function names stay English** (`IF`, `MEDIAN`, `IFERROR`); Excel localizes display itself.
- **XlsxWriter writes, openpyxl only reads (in tests).** Formulas ship without cached results —
  Excel recomputes on open (LibreOffice: Ctrl+Shift+F9).
- LLM output is pydantic-validated with **one repair retry**; missing fields → blank cells + gap report.

## Build / test (PowerShell, from this folder)
```powershell
.venv\Scripts\Activate.ps1
pip install -e .[llm,dev]          # first time
pytest                              # full suite
finauto run samples\X.pdf --ticker XXXX.IS --peers A.IS,B.IS   # CLI smoke test
```
- The load-bearing correctness test is `tests/test_workbook.py::test_every_division_is_error_guarded`
  (scans all formulas for IFERROR coverage). It must stay green — if you add a division, guard it.
- Unit tests use **fixtures**, never live network/LLM calls.

## Gotchas (more in README "Known caveats")
- yfinance BIST fundamentals are often stale/missing → always surface the gap report; degrade to blanks.
- Post-2022 BIST figures are TMS-29/IAS-29 inflation-restated → nominal TRY growth is distorted.
- Scanned/image-only PDFs are out of scope (text PDFs only).
- API keys live in `.env` only (gitignored; the workspace secrets hook enforces this).

## Roadmap
Phase 2 = KAP auto-download + FX restatement + watchlists; Phase 3 = FastAPI/React SaaS reusing
this package as a library. Keep the package import-clean so Phase 3 can `import finauto`.
