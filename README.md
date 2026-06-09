# FinAuto-Valuation Engine

Automated financial engineering pipeline: drop in corporate financial report
PDFs (BIST/KAP focus, works for any industrial ticker) and get back a
professional, fully formula-linked 6-tab Excel valuation model (10-year DCF +
peer relative valuation) with an automated AL / TUT / SAT signal.

```
finauto extract  : PDF(s) ──LLM──▶ financials.json   (pydantic-validated)
finauto market   : tickers ──yfinance──▶ market.json (target + peers)
finauto build    : financials.json + market.json ──▶ model.xlsx
finauto run      : all three chained
```

## Setup

Requires Python 3.11+.

```powershell
cd finauto
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .[llm,dev]
copy .env.example .env   # then fill in GEMINI_API_KEY and/or ANTHROPIC_API_KEY
```

The Excel engine and market-data stages work without any API key — keys are
only needed for `extract` / `run` (the LLM PDF parsing stage).

## Usage

```powershell
# 1. Extract historicals from one or more report PDFs
finauto extract samples\thyao_2025_annual.pdf --ticker THYAO.IS

# 2. Pull live market data for the target and its peers
finauto market --ticker THYAO.IS --peers PGSUS.IS,RYAAY,WIZZ.L,EZJ.L

# 3. Build the workbook
finauto build -f THYAO_IS_financials.json -m THYAO_IS_market.json -o THYAO_valuation.xlsx

# Or everything at once
finauto run samples\thyao_2025_annual.pdf --ticker THYAO.IS --peers PGSUS.IS,RYAAY,WIZZ.L,EZJ.L
```

Useful flags:

- `--provider gemini|claude` — choose the extraction LLM (default from `.env`)
- `--locale tr|en` — workbook label language (default `tr`)
- `--assumptions assumptions.yaml` — override derived assumptions; keys match
  the `Assumptions` schema (`risk_free_rate`, `terminal_growth`, `tax_rate`, …)
- `--force` — bypass the financial-institution sector guard (banks, insurers
  and REITs are rejected by default; FCFF valuation does not apply to them)

## The workbook

| Sheet | Contents |
|---|---|
| `01_Assumptions` | All user inputs (blue cells). Every input has a defined name (`RiskFree`, `Growth1`, `WACC`-feeding cells…). Change anything here and the target price on sheet 06 recomputes. |
| `02_Historical_Financials` | Extracted IS/BS/CF lines, years as columns; subtotals and derived ratios are formulas. |
| `03_WACC_Calculation` | Peer beta matrix (unlevered via `MAX(0,debt)` clamp), median asset beta relevered to the target, CAPM Ke (+ country risk premium), Rd from interest/avg-debt with Rf+spread fallback, market-value-weighted WACC. |
| `04_DCF_Model` | Year 0–10 FCFF forecast — zero hardcoded numbers; Gordon-growth terminal value guarded against `WACC <= g`. |
| `05_Relative_Valuation` | Peer EV/EBITDA, EV/Sales, P/E (formula-only off sheet 03), medians, and three implied-price tracks each applying the net-debt bridge. |
| `06_Valuation_Summary` | Weighted target price (default 70% DCF / 30% multiples), upside vs. current price, automated `AL`/`TUT`/`SAT` signal, hard-currency conversion via the FX-rate input. |

Conventions: blue-on-cream cells are inputs; everything else is a formula.
All monetary values are written in full currency units. Every division is
wrapped in `IFERROR` (enforced by tests), so missing data degrades to blank
cells instead of `#DIV/0!` cascades.

## Tests

```powershell
pytest
```

The workbook test builds a model from the fixtures and reads it back with
openpyxl, asserting formula strings, defined names, and that every division
is error-guarded.

## Known caveats

- yfinance fundamentals for BIST tickers can be stale or missing; the CLI
  prints a gap report and the workbook degrades those cells to blanks.
- Post-2022 BIST financials are inflation-restated (TMS-29 / IAS 29): nominal
  TRY growth rates are distorted. Review the derived `growth_stage1` and
  consider valuing in a hard currency (Phase 2 will automate FX restatement).
- Scanned (image-only) PDFs are out of scope for v1; KAP filings are text PDFs.
- XlsxWriter writes formulas without cached results: Excel recalculates on
  open; LibreOffice users may need Ctrl+Shift+F9.

## Roadmap

- **Phase 2** — KAP disclosure scraping (auto PDF download per ticker/period),
  live price refresh, sector assumption presets, FX restatement, watchlists.
- **Phase 3** — FastAPI backend reusing this package as a library, PostgreSQL
  storage, React + Recharts frontend (football field chart, assumption
  sliders), Docker deploy. The JSON intermediates become the API payloads.

See [plan.md](plan.md) for the full architecture document.
