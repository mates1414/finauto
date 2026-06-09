# FinAuto-Valuation Engine — Implementation Plan

## Context

Goal: an automated pipeline that turns raw corporate financial PDFs (BIST focus, but ticker-agnostic) into a professional, fully formula-linked 6-tab Excel valuation model (DCF + relative valuation). Manual data entry is the bottleneck this removes; changing any assumption cell must dynamically recompute the target price.

Decisions confirmed:
- **Build Phase 1 (MVP CLI) now**; plan documents Phase 2/3 roadmap so the architecture supports them.
- **Peer/market data via yfinance**, generic for any ticker (peers passed per run, not hardcoded airlines).
- **Pluggable LLM provider layer** (Gemini 2.5 and Claude implementations behind one interface).
- **Turkish labels by default** with a locale dictionary so English can be switched on later. Sheet *names* stay English/ASCII (`01_Assumptions`…) for stable cross-sheet formula references; only row/header labels localize.

## Architecture: decoupled 3-stage pipeline with JSON intermediates

Each stage runs and tests independently; the Excel engine never depends on the LLM or network:

```
finauto extract  : PDF(s) ──LLM──▶ financials.json   (pydantic-validated)
finauto market   : tickers ──yfinance──▶ market.json (target + peers snapshot)
finauto build    : financials.json + market.json + assumptions ──▶ model.xlsx
finauto run      : all three chained
```

## Project layout (src layout, pip-installable package — Phase 3 reuses it as a library)

```
finauto/
├── plan.md                     # this plan, kept in-repo
├── pyproject.toml              # deps + console script "finauto"
├── .env.example                # GEMINI_API_KEY, ANTHROPIC_API_KEY, FINAUTO_LLM_PROVIDER
├── README.md
├── src/finauto/
│   ├── cli.py                  # Typer app: extract / market / build / run
│   ├── config.py               # pydantic-settings: provider, locale, defaults
│   ├── schemas.py              # pydantic contracts between all stages
│   ├── labels.py               # LABELS = {"tr": {...}, "en": {...}}
│   ├── assumptions.py          # derive defaults from historicals + yaml overrides
│   ├── ingestion/
│   │   ├── base.py             # Extractor protocol + provider factory
│   │   ├── gemini.py           # google-genai, native PDF input, structured output
│   │   ├── claude.py           # anthropic SDK, PDF document block + tool-use schema
│   │   ├── prompts.py          # extraction instructions (TR financial statement terms)
│   │   └── pdf_loader.py       # page filtering for oversized PDFs
│   ├── marketdata/yahoo.py     # snapshot(ticker) -> TickerSnapshot; beta fallback regression
│   ├── validation/
│   │   ├── sector_guard.py     # reject banks/insurance/REITs → SectorNotSupportedError
│   │   └── sanity.py           # net-debt clamps, missing-field report, unit normalization
│   └── engine/
│       ├── builder.py          # WorkbookBuilder: orchestrates sheets, defined names
│       ├── formulas.py         # ref helpers, iferror(), column utilities
│       ├── styles.py           # XlsxWriter formats: inputs blue, formulas black, %, x
│       └── sheets/             # one module per tab (s01..s06)
├── tests/
│   ├── fixtures/financials_sample.json, market_sample.json
│   └── test_*.py               # schemas, sanity, formulas, workbook read-back
└── samples/                    # user drops PDFs here
```

Key choices: **XlsxWriter** to generate, **openpyxl** only in tests to read back. **Typer + rich** CLI, **pydantic v2** everywhere. Excel formulas always use **English function names** (`IF`, `MEDIAN`, `IFERROR`) — Excel localizes display automatically on Turkish installs.

## The 6-sheet blueprint (hardcoded values ONLY on sheets 2 & 3; sheet 1 holds user inputs)

**01_Assumptions** — input dashboard; every input cell gets a defined name (`RiskFree`, `ERP`, `CRP`, `TaxRate`, `FXRate`, `Growth1`, `Growth2`, `TerminalGrowth`, `EBITMargin`, `CapExPct`, `NWCPct`, `DAPct`, `WeightDCF`, `WeightMultiples`, `SignalThreshold`, `CurrentPrice`, `SharesOut`). Cell map: B4 Rf, B5 ERP, B6 CRP, B7 Tax, B8 FX; B11 g1, B12 g2, B13 g_term, B14 EBIT margin, B15 CapEx/Sales, B16 NWC/Sales, B17 D&A/Sales; B19/B20 valuation weights, B21 signal threshold; B23 current price, B24 shares outstanding (prefilled from market.json).

**02_Historical_Financials** — years as columns, IS/BS/CF rows; raw values hardcoded, subtotals (Gross Profit, EBIT) as formulas; derived metrics block (net debt, growth %, margins) for assumption defaults.

**03_WACC_Calculation** — hosts ALL hardcoded peer raw data (sheet 5 references it): peer matrix (price, shares, mkt cap, debt incl. leases, cash, EBITDA, sales, net income, levered beta) with formula columns D/E and unlevered beta (`MAX(0,debt)` clamp), `MEDIAN` unlevered beta, relever at target D/E, `Ke = Rf + β·ERP + CRP`, `Rd = IFERROR(interest/avg debt, Rf + spread)`, market-value weights, `WACC` defined name. Missing yfinance beta → python-side weekly-returns regression vs the suffix-matched index (`^XU100` for `.IS`).

**04_DCF_Model** — Year 0–10 columns, zero hardcoded numbers. Revenue growth from `Growth1`/`Growth2`; EBIT margin, D&A/CapEx/ΔNWC as % of sales; NOPAT → FCFF; discount factor `=1/(1+WACC)^t`; Gordon TV wrapped in IFERROR; EV − Net Debt (from 02, incl. leases) → equity → `DCFImpliedPrice`.

**05_Relative_Valuation** — formula-only multiples off sheet 3 raw data: EV/EBITDA, EV/Sales, P/E per peer (all IFERROR-wrapped, negative-earnings P/E blanked), MEDIAN row, three implied-price tracks each enforcing the net-debt bridge (Implied EV − Net Debt = Equity → /Shares).

**06_Valuation_Summary** — method/price/weight matrix, weighted target via SUMPRODUCT normalized by available weights, upside vs `CurrentPrice`, signal `AL/TUT/SAT` (BUY/HOLD/SELL in EN) at `SignalThreshold`, hard-currency conversion row via `FXRate`.

## Safeguards

- Sector guard (banks/insurance/REIT → exception, `--force` to bypass).
- `max(0, debt)` clamps python-side AND in unlevering formulas.
- Every division wrapped in `IFERROR` (enforced by a test that scans all formulas).
- v1 models in the statement's reporting currency; sheet 6 converts outputs via `FXRate`. TMS-29/IAS-29 hyperinflation restatement caveat documented.
- LLM output pydantic-validated with one schema-repair retry; missing fields degrade to blank cells.

## Milestones (Phase 1)

1. Scaffold + contracts (pyproject, schemas, labels, fixtures, git init)
2. Excel engine core + sheets 01/02/04 → first workbook from fixture JSON
3. Market data + sector guard + sheets 03/05/06
4. LLM ingestion (pluggable) + `finauto extract` / `finauto run`
5. Polish: styles, README, full test pass

## Verification

- `pytest`: build from fixtures → reopen with openpyxl → assert formula strings, defined names, IFERROR coverage scan.
- Optional math check with the `formulas` package vs an independent Python DCF reference.
- Manual: `finauto market --ticker THYAO.IS --peers PGSUS.IS,RYAAY,WIZZ.L,EZJ.L` + `finauto build`; open in Excel, change `01_Assumptions!B11`, watch sheet-6 target move.
- Negative tests: bank ticker rejected; zero-debt peer produces no `#DIV/0!`.

## Phase 2 roadmap (architecture ready, not built)

KAP disclosure scraping (no official API — frontend JSON endpoints) for auto PDF download per ticker/period; live price refresh; sector assumption presets; full FX restatement of historicals; watchlist batch mode.

## Phase 3 roadmap (SaaS)

FastAPI backend importing `finauto` as a library (async extraction jobs), PostgreSQL (users/watchlists/snapshots), React + Recharts frontend (football field, assumption sliders), Docker on AWS/GCP. The JSON intermediates become the API/DB payloads.

## Known risks

- yfinance fundamentals for BIST tickers can be stale/missing → completeness report; missing peer fields degrade to blank + IFERROR.
- Scanned (non-text) PDFs need OCR — out of scope v1; KAP PDFs are text-based.
- XlsxWriter writes formulas without cached results — Excel computes on open; LibreOffice users must force recalc.
