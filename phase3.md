# FinAuto — Phase 3 Feasibility Study & Implementation Plan

Autonomous competitor discovery · bi-directional Excel workflow · web frontend.
Builds on the Phase 1 MVP and the Phase 2 roadmap in [plan.md](plan.md). The Phase 3
SaaS reuses this package **as a library** — the Pydantic JSON intermediates are the API/DB
contract.

---

## Context

Three enhancements were requested on top of the existing CLI pipeline
(`extract → market → build`):

1. **Competitor discovery (autonomous search)** — let the LLM research and propose peers when
   the user doesn't supply them.
2. **Bi-directional Excel workflow** — generate the editable workbook, let the user correct it,
   then generate a final strategic report from the uploaded, corrected file.
3. **Frontend UI** — a wizard for non-technical users that ties the whole flow together.

`finauto` already provides the hard parts: the decoupled 3-stage pipeline, Pydantic contracts
(`schemas.py`), a pluggable LLM layer (`ingestion/base.py`), and a formula-linked workbook whose
**blue input cells are already the edit surface**. So requests 2 and 3 are essentially the Phase 3
SaaS, and request 1 is a new capability that suggests peers *per run* (dynamic — consistent with
finance-invariant #7, "no hardcoded tickers/peers").

---

## Part 1 — LLM & Architecture Recommendation

### It's tool-use + structured outputs, not RAG
- **RAG is the wrong default.** Per-run data is tiny and structured (one company + a few peers) —
  nothing to vector-index. RAG only earns its place later if a methodology/sector knowledge base
  is added (optional, Phase 3+).
- **Server-side web search is the discovery primitive.** Anthropic's `web_search_20260209`
  (+ `web_fetch_20260209`) with **dynamic filtering** (Opus 4.8 / Sonnet 4.6 — Claude filters
  results in code before they hit context) does live research server-side and returns **citations**.
  No scraping infra.
- **Structured outputs** (`output_config.format` / `messages.parse()` with the existing Pydantic
  models) bind extraction and discovery to the schema with a repair retry — the package already
  validates-then-repairs.
- **Tier = Workflow** (code-orchestrated tool use), not a full agent. The backend owns the loop;
  each stage is a few bounded calls. Reserve **Managed Agents** for a later fully-autonomous
  analyst — overkill at this scale.

### Provider-agnostic by design
finauto's LLM layer is **pluggable** (`ingestion/base.py`: `Extractor` Protocol + `get_extractor`
factory; Gemini default, Claude alternative). Every new Phase-3 capability follows the same rule —
**add a provider by implementing a Protocol, never by branching in callers** (finauto/CLAUDE.md).
Only **web search is provider-specific**; everything else (extraction, report writing) is plain
generation any provider does.

| Capability | Provider-neutral? | How each provider does it |
|---|---|---|
| PDF extraction | ✅ already pluggable | Gemini (native PDF) / Claude (PDF blocks) / others |
| Report writing | ✅ | any chat model (Gemini / Claude / OpenAI / local) |
| **Competitor discovery (web search)** | ⚠️ provider-specific | Gemini **Google Search grounding** · Anthropic **`web_search` tool** · or **provider-neutral**: an external Search API (Tavily/Serper/Bing) as a tool + any chat model |

### Provider / model routing (defaults; all overridable per stage)
| Stage | Default | Strong alternative | Why |
|---|---|---|---|
| Extraction | **Gemini 2.5 Pro** (project default, native PDF) | Claude Sonnet 4.6 | schema-bound + repair-retried; choose on accuracy/cost per filing set |
| Discovery | **Gemini + Google Search grounding** | Claude Opus 4.8 + `web_search` | both return citations; or Search-API + any model for full neutrality |
| Report | **Claude Opus 4.8** or **Gemini 2.5 Pro** (streamed) | — | narrative quality; pick by preference/cost |

Provider **and** model are config per stage (Part 4 · A6); no stage is hard-wired to one vendor.

---

## Part 2 — Cost Estimation (100 reports/month)

**Token pricing (per 1M, Claude API reference, cached 2026-06-04):** Opus 4.8 $5 / $25 ·
Sonnet 4.6 $3 / $15 · Haiku 4.5 $1 / $5. **Batch API = 50% off** (async ≤24 h). **Prompt caching:**
reads ≈0.1× input, 5-min writes 1.25× (min cacheable prefix on Opus 4.8 = 4,096 tok). Web-search
tool adds a small per-search fee (~$10/1k searches historically — **confirm on the current pricing
page**; the docs pricing URL 404'd at time of writing).

**Per-report token assumptions:** extraction ~120k in / 4k out · discovery ~15k in / 2k out (+~4
searches) · report ~30k in / 8k out → **~165k in / ~14k out per report**.

| Config | Per report | **Per month (×100)** |
|---|---|---|
| All-Opus, standard | ~$1.23 | ~$123 |
| All-Sonnet, standard | ~$0.74 | ~$74 |
| **Recommended split** (Sonnet extract / Opus discover+report) | ~$0.94 | **~$94** |
| Recommended split + **Batch** | ~$0.55 | **~$55** |
| Recommended split + Batch + caching | ~$0.50 | **~$50** |

Add-ons: web search ~$4/mo, storage + Postgres + small VM ≈ $20–60/mo. **Headline: ~$50–95/month —
token cost is not the constraint at this scale.** The cost centers are engineering (the Excel
round-trip) and the frontend.

> **Provider-dependent.** The table anchors on Claude token prices (authoritative reference); Gemini /
> OpenAI / others differ — re-baseline with each provider's pricing and token-count tool. Because
> routing is per stage, you can run the cheapest adequate provider for each (e.g. Gemini extraction +
> Gemini-grounded discovery can land well under the Claude figures).

---

## Part 3 — Technical Feasibility (summary)

**1. Competitor discovery — ✅** The LLM + web search (Gemini Google Search grounding **or** Claude `web_search`) returns a structured peer list
(`{name, ticker?, exchange, rationale, confidence}`); resolve names→tickers and **validate every
candidate against `marketdata/yahoo.snapshot`** (drop unresolved → auto-filters hallucinations).
Keep a **human-confirm** step; peers still resolve per run (invariant #7).

**2. Bi-directional Excel — ✅** The workbook's blue cells are the edit surface. The one gotcha:
XlsxWriter ships formulas **without cached values**, so on upload you must **recalc before reading**
(headless LibreOffice or the `formulas` lib) then read with openpyxl `data_only=True`. Re-parse into
the Pydantic contract (same `validation/sanity.py` guards), **diff** edited vs original, and generate
a **grounded** report (cite real numbers — enforces invariant #8). Lock formula cells so users edit
only blue inputs.

**3. Frontend — ✅** FastAPI imports `finauto` as a library (JSON intermediates = payloads); async
jobs (extraction/report are minutes-long) + Postgres + object storage; React 5-step wizard with a
streamed report. Secrets stay server-side.

---

## Part 4 — Detailed Implementation Plan

Four phases. **Phase A** extends the existing `finauto` package (CLI-first, fully testable without a
UI). **Phases B/C** live **outside** the package (see the repository decision below). **Phase D**
(cross-cutting evals/hardening) is documented at the **end of this file**, after the A/B/C build
sequence, together with the Phase A implementation-status / review notes.

Layering rule carried over: **engine stays pure; network/LLM only at the edges.** Web search lives in
`ingestion/`/`marketdata/` edge modules; the report generator is an edge module; the engine never
imports an LLM SDK.

### Repository layout (decision)
**Do not nest the API or frontend inside `finauto`.** `finauto` is a self-contained, pip-installable
**Python library** with its own repo; bundling a web service + a Node/React app into it would break
that boundary, mix a JS toolchain into a Python package, and couple release cadences. The clean seam
is the **JSON intermediates** — the API depends on `finauto` as an installed library.

- **Recommended now — one new repo `finauto-saas/`** with two subfolders: `api/` (FastAPI, its own
  Python `.venv`) and `web/` (React, its own `package.json`). One repo buys atomic full-stack PRs, a
  single CI/issue tracker, and simple local dev for a small team, while `finauto` stays clean.
- **Alternative at scale — two repos** `finauto-api/` + `finauto-web/`, for independent deploy/release
  per side. Split out of `finauto-saas/` once the API and frontend need separate cadences or teams.
- Either way honors the workspace convention ("each new app its own repo; depend on `finauto` as a
  library, not by nesting"). No `.venv` or `package.json` ever lands in the `finauto` repo;
  `finauto-saas/api` installs `finauto` as a dependency (path/editable in dev, pinned in prod).

### Phase A — LLM capability layer (in `finauto`)

#### A1. Schemas — `src/finauto/schemas.py`
Add contracts (these become API/DB payloads later):
```python
class PeerCandidate(BaseModel):
    name: str
    ticker: Optional[str] = None
    exchange: Optional[str] = None
    rationale: Optional[str] = None
    confidence: float = 0.0          # 0..1 from the model
    resolved: bool = False           # set True after yahoo validation
    market_cap: Number = None        # filled on resolution, for sanity sort

class PeerSuggestionSet(BaseModel):
    target: str
    candidates: list[PeerCandidate] = Field(default_factory=list)
    dropped: list[str] = Field(default_factory=list)   # name + reason, audit trail
    source: Optional[str] = None     # "Claude web_search" + date

class EditNote(BaseModel):           # one user correction, for the report prompt
    path: str                        # e.g. "2025.income_statement.revenue"
    old: Number = None
    new: Number = None

class StrategicReport(BaseModel):
    ticker: str
    markdown: str                    # the narrative
    grounded_figures: list[str] = Field(default_factory=list)  # cells/values cited
    model: Optional[str] = None
```
Reuse `Number`, `CompanyFinancials`, `Assumptions`, `MarketData` as-is.

#### A2. Peer discovery — new `src/finauto/marketdata/web_research.py` (edge, pluggable)
Mirror `ingestion/base.py`: a `PeerResearcher` Protocol + `get_peer_researcher(settings)` factory —
**add a provider by implementing the Protocol, never by branching in callers.**
- `PeerResearcher.discover(target_name, *, sector=None, country="Türkiye", n=5) -> PeerSuggestionSet`.
- Implementations (each behind the factory, selected by `discover_provider`):
  - `GeminiPeerResearcher` — Gemini call with **Google Search grounding** enabled; map grounded
    results → `PeerSuggestionSet` (parse citations into `source`).
  - `ClaudePeerResearcher` — `client.messages` with `web_search_20260209` (+ `web_fetch_20260209`),
    `thinking={"type":"adaptive"}`, and `output_config.format` bound to `PeerSuggestionSet`.
  - `SearchApiResearcher` (optional, fully provider-neutral) — an external Search API (Tavily/Serper)
    as a tool + the configured chat model, for when search must be decoupled from the LLM vendor.
  - Shared system prompt: "propose listed comparables on the same exchange/sector; return tickers
    where known; never invent tickers — leave blank if unsure."
- `resolve_and_validate(suggestion, settings) -> PeerSuggestionSet` (**provider-independent**): for
  each candidate resolve the ticker (provider-given or a cheap suffix-guess like `*.IS`), call
  existing `marketdata/yahoo.snapshot`; set `resolved=True`/`market_cap` on success, else move to
  `dropped` with a reason. **This is the hallucination filter regardless of who searched.**
- **Deps:** none beyond the chosen provider SDK (`google-genai` / `anthropic`, already in the `llm`
  extra). The optional Search-API path adds a small `httpx` client + that service's key in `.env`.

#### A3. CLI wiring — `src/finauto/cli.py`
- `finauto discover --ticker X [--name "..."] [--sector "..."]` → prints the suggested peer table
  (resolved first, by market cap) + dropped list; writes `results/<T>/peers.json`.
- `--auto-peers` flag on `run`/`build`: if `--peers` is omitted, run discovery, **print the list and
  require confirmation** (or `--yes` to accept top-N non-interactively), then feed accepted tickers
  into the existing peer path. Invariant #7 preserved (suggest → confirm → per-run).
- Reuse `_results_dir`, `_print_warnings`.

#### A4. Excel read-back — new `src/finauto/engine/readback.py` (pure-ish; recalc is the only edge)
- `recalc(path) -> Path`: materialize formula values. Primary: headless LibreOffice
  (`soffice --headless --convert-to xlsx --outdir ...`); fallback: the `formulas` library (already
  used for verification). Detect availability; clear error if neither present.
- `read_inputs(path) -> tuple[CompanyFinancials, Assumptions, dict]`: openpyxl `data_only=True`,
  reading the **blue input cells and computed outputs** by their **symbolic row maps** (`Sheet2Layout`
  ROWS etc.) so renumbering stays transparent. Returns financials, assumptions, and a `computed`
  dict (target price, WACC, multiples, signal) from sheet 06/03.
- `diff_inputs(original: CompanyFinancials, edited: CompanyFinancials) -> list[EditNote]`.
- Re-run `validation/sanity.reconcile_financials` + `financials_gap_report` on the edited inputs.
- **Harden the emitted workbook** (small change in `engine/builder.py`/`styles.py`): enable sheet
  protection with blue input cells unlocked, so users edit only intended cells.

#### A5. Report generator — new `src/finauto/report/generator.py` + `report/prompts.py` (edge, pluggable)
A `ReportWriter` Protocol + `get_report_writer(settings)` factory (Gemini / Claude / others) — report
writing is plain generation, so it is fully provider-neutral.
- `ReportWriter.generate(report_ctx, *, stream=True) -> StrategicReport`. Assemble a
  **grounded context block**: computed outputs, peer comparison table, the gap report, and the
  `EditNote` diff. System prompt enforces: *cite every figure from the provided data; never invent
  numbers; flag TMS-29/FX inflation caveats; structure = thesis → DCF → relative val → risks →
  AL/TUT/SAT rationale.* Stream tokens.
- Output markdown; optional `report/docx.py` (python-docx) or the code-execution skill for a PDF/DOCX
  artifact.
- CLI: `finauto report results/<T>/<edited>.xlsx [--out report.md] [--docx]` → recalc → read_inputs →
  diff → generate.
- **Dependency:** new `report` extra — `["python-docx>=1.1", "formulas>=1.2"]` (LibreOffice is an
  external binary, documented in README, not a pip dep).

#### A6. Provider routing & cost controls — `src/finauto/config.py` + `llm/batch.py`
- Per-stage **provider + model** in `Settings`: `extract_provider`/`extract_model`,
  `discover_provider`/`discover_model`, `report_provider`/`report_model` — each defaults per the
  routing table, overridable via env/`.env` or CLI. The existing `llm_provider` stays as the global
  fallback so current behavior is unchanged.
- `batch.py`: provider-aware batch submission where supported (Anthropic Batch API = 50% off; Gemini
  batch mode where available) for non-interactive extraction/report jobs; CLI keeps the sync path.
- **Prompt/context caching** where the provider supports it (Anthropic `cache_control`; Gemini
  context caching) on the stable system + JSON-schema prefix.

#### A — Tests (`tests/`, fixtures only, no live network)
- `test_web_research.py`: `resolve_and_validate` drops a candidate whose snapshot fails; keeps a real
  one; parses a saved structured response fixture into `PeerSuggestionSet`.
- `test_readback.py`: build fixture workbook → recalc (skip if no LibreOffice/`formulas`) →
  `read_inputs` round-trips revenue/assumptions; `diff_inputs` reports a changed cell.
- `test_report.py`: `generate` on a fixture context (monkeypatched LLM) returns markdown that
  contains the provided target price and contains no figure absent from the context (grounding
  assertion).

**Phase A milestone:** `finauto discover` + `finauto report` work end-to-end from the CLI; full
`pytest` green; manual smoke on BIMAS (`results/BIMAS_IS/`).

### Phase B — Service layer (`finauto-saas/api/`)

```
finauto-saas/api/
├── pyproject.toml            # depends on finauto (path/editable), fastapi, uvicorn,
│                             # sqlalchemy, alembic, arq (or rq), pydantic-settings, boto3/minio
├── src/finauto_api/
│   ├── main.py               # FastAPI app, CORS, routers
│   ├── deps.py               # settings, db session, current-user
│   ├── models.py             # SQLAlchemy: User, Job, Snapshot (stores the JSON intermediates)
│   ├── schemas.py            # request/response = finauto Pydantic contracts re-exported
│   ├── jobs/                 # arq tasks: extract_job, report_job (call finauto + Batch API)
│   ├── routers/
│   │   ├── extract.py        # POST /extract  (PDF upload → job)   GET /jobs/{id}
│   │   ├── peers.py          # POST /peers/suggest
│   │   ├── workbook.py       # POST /build  ·  GET /workbook/{id}   (download .xlsx)
│   │   └── report.py         # POST /report (upload edited .xlsx)  GET /report/{id} (SSE stream)
│   └── storage.py            # object storage for PDFs/xlsx (S3/MinIO or Files API)
└── tests/                    # httpx AsyncClient against the routers; finauto mocked
```
- **Async** because extraction/report are minutes-long (and may be batched). Job runner = arq/RQ;
  Postgres for users/jobs/snapshots; object storage for PDFs/xlsx.
- **Stream the report** over SSE (`GET /report/{id}`).
- **Security:** API keys server-side only; per-user isolation; nothing key-shaped to the client
  (mirror the workspace secrets rule). Auth = session/JWT.
- The JSON intermediates flow unchanged from CLI → API → DB (the contract pays off here).

### Phase C — Frontend (`finauto-saas/web/`)

- **React + Vite + TypeScript**, Recharts for the football-field chart, i18n (TR default / EN — match
  the workbook `locale`).
- **5-step wizard** for non-technical users:
  1. **Upload PDFs** (dropzone) → kicks off `extract`.
  2. **Confirm company + review/edit suggested peers** (`peers/suggest`; editable chips; resolved
     peers pre-checked, dropped ones shown with reason).
  3. **Download Excel** + on-screen "edit the blue cells, then re-upload" guidance.
  4. **Upload edited Excel** → kicks off `report`.
  5. **Read the streamed report** — rendered markdown + football-field chart + assumption sliders
     (sliders re-`build` for what-ifs), AL/TUT/SAT badge, export to PDF/DOCX.
- Streaming report view (consume SSE); job-status polling for extract/build.
- No CLI exposed; errors and the gap report surfaced as friendly warnings.

---

## Sequencing & dependencies

| Phase | Ships | New deps |
|---|---|---|
| A | `discover` + `report` CLI, locked workbook, per-stage provider routing | provider SDK (`google-genai` / `anthropic`, have them); `report` extra: `python-docx`, `formulas`; LibreOffice (external) |
| B | `finauto-saas/api` service | fastapi, uvicorn, sqlalchemy, alembic, arq, storage client |
| C | `finauto-saas/web` wizard | React/Vite/TS, Recharts, i18n |
| D | evals/dashboards | pytest goldens, cost telemetry |

Phase A is independently valuable and fully testable before any UI exists — do it first.

## Verification
- **A:** `pytest` from `finauto/`; `finauto discover --ticker BIMAS.IS` returns resolved peers;
  `finauto report results/BIMAS_IS/<edited>.xlsx` produces a grounded markdown report; the
  no-unguarded-division and grounding tests stay green.
- **B:** `httpx` integration tests hit each router with `finauto` mocked; one real end-to-end run
  (upload PDFs → download xlsx → upload edited → stream report) against a dev Postgres.
- **C:** Cypress/Playwright walk the 5 wizard steps against the dev API.
- **D:** golden-set extraction diff and the report-grounding assertion run in CI.

## Risks
- **Web search reliability for niche BIST names** → always validate peers against live data; allow
  manual add. **Excel read-back** → never trust uncached formula values; recalc on upload.
  **Report hallucination** → grounding prompt + automated grounding check (invariant #8). **Peers
  stay per-run** (invariant #7). **Inflation/FX caveats** must surface in the narrative.

---

## Phase D — Evals & hardening (cross-cutting, deferred)

> Moved here from the Part 4 sequence: Phase D is not part of the A/B/C build order — it is an
> ongoing hardening track layered on top once A (and the grounding seed) exists. The Phase A
> `report.ungrounded_figures` check is the seed for the grounding gate below (see the open issue
> on its false-positive rate before wiring it as a hard CI failure).

- **Extraction accuracy** golden set (a few hand-checked filings) with field-level diff in CI.
- **Report-grounding check** — automated assert that every numeric token in the narrative traces to a
  value in the provided context (no fabrication); fail the job otherwise.
- Cost/latency dashboards; per-stage token + batch usage; model-routing A/B.
- Carry the finance invariants into the narrative layer (TMS-29/FX caveats, WACC>g, net debt incl.
  leases) so the report can't contradict the model.

---

## Phase A — implementation status & review notes (reviewed 2026-06-13)

**Status: Phase A is implemented and green** (48 tests pass; new files ruff-clean). Delivered:
`finauto discover` + `finauto report` CLI; `marketdata/web_research.py` (Gemini-grounding /
Claude-`web_search` researchers + `resolve_and_validate` hallucination filter); `engine/readback.py`
(`recalc` → `read_inputs` → `diff_inputs`); `report/` (grounded generator + `ungrounded_figures`);
per-stage routing in `config.Settings.stage()`; `llm/batch.py` (Anthropic Batch + prompt caching);
workbook sheet-protection hardening; the `report` optional-dependency extra.

**Update (2026-06-13, later): Phases B & C are now implemented** in the sibling `finauto-saas/`
repo (`api/` = FastAPI service, `web/` = React/Vite wizard), with `finauto` consumed as an editable
library. API: JWT auth, `extract`/`peers`/`workbook`/`report` routers, pluggable queue
(in-memory/arq) + storage (local/S3), and SSE report streaming — **11 API tests pass**. Web: 5-step
wizard, builds clean (tsc+vite), now styled with Tailwind v4. See the post-review fixes log below.

### Open issues found in review (Phase A)

1. **Extraction stage routing is dead config (functional gap).** `config.Settings` exposes
   `extract_provider` / `extract_model` and `stage("extract")`, and A6 promises per-stage routing for
   extraction — but `ingestion/base.get_extractor` still reads `settings.llm_provider` /
   `gemini_model` / `claude_model` directly and never calls `stage("extract")`. So
   `FINAUTO_EXTRACT_PROVIDER` / `FINAUTO_EXTRACT_MODEL` currently have **no effect**; only the global
   `--provider` works for extraction. Discovery and report *are* wired through `stage()`. **Fix:** have
   `get_extractor` resolve `provider, model = settings.stage("extract")`.

2. **`python-docx` is declared but unused; `--docx` not implemented.** A5 specifies
   `finauto report ... [--docx]` and an optional `report/docx.py`. The `report` command has no
   `--docx` flag and there is no `report/docx.py`, so `python-docx>=1.1` in the `report` extra is a
   dead dependency. **Fix:** either add a minimal markdown→docx export, or drop `python-docx` from the
   extra until it is built (`formulas` is genuinely used by the recalc fallback and should stay).

3. **Grounding check is heuristic and false-positive-prone — do not hard-fail CI on it yet.**
   `ungrounded_figures` matches raw number tokens against exact context values (×100/÷100 variants).
   A narrative that writes a figure in scaled/worded form — “₺50 billion”, “50.0bn” instead of the
   full `50,000,000,000` — or a model-computed ratio that isn't already a context value, is flagged as
   ungrounded. In the CLI this is only a **warning** (correct), but as Phase D's CI gate it would be
   too noisy. **Fix before Phase D:** scale-/unit-aware matching (recognize billion/million wording and
   tolerance bands) before promoting it to a hard failure.

4. **Claude `pause_turn` loop drops intermediate turns (minor correctness).** In
   `ClaudePeerResearcher.discover`, each `pause_turn` rebuilds `messages = [prompt, last_assistant]`,
   discarding earlier assistant turns and their tool context. Most web searches finish in one turn, so
   this rarely bites, but a multi-pause flow loses history. **Fix:** append to a growing message list
   instead of replacing it.

5. **`SearchApiResearcher` (provider-neutral Tavily/Serper path) not implemented.** Marked *optional*
   in A2, so not a defect — but the “full provider neutrality” framing isn't realized: discovery is
   Gemini/Claude only. Worth a note so the claim and the code stay honest.

Items 1–2 are quick, in-scope fixes; 3–4 are correctness/robustness follow-ups; 5 is an optional
extension. None block the Phase A milestone.

---

## Phase B/C — post-review fixes (2026-06-13)

Issues found and fixed in the `finauto-saas/` repo after the first end-to-end review:

1. **API test suite hung indefinitely (blocker).** `routers/report.py` and `jobs/tasks.py` did
   `from ..deps import SessionLocal`, capturing the original file-DB session at import time; the test
   override (an in-memory DB) never reached them. The SSE stream endpoint then couldn't find the
   job, fell through, and blocked forever on `pubsub.subscribe`. **Fix:** reference `deps.SessionLocal()`
   module-qualified everywhere, and make the SSE generator emit `[DONE]` and return on job-not-found.
   Suite now completes: **11 passed**.
2. **Ticker smuggled through `Job.error`.** All three of `extract`/`report`/`tasks` overloaded the
   error column as a context channel. **Fix:** added a dedicated `Job.ticker` column.
3. **Hardcoded `d:/projects/finance/finauto/betaemerg.xls`** in `workbook.py`. **Fix:** a
   `DAMODARAN_BETA_PATH` setting + auto-location next to the installed `finauto` package.
4. **Invalid CORS** (`allow_origins=["*"]` with `allow_credentials=True`). **Fix:** explicit,
   configurable `CORS_ORIGINS` allow-list.
5. **Frontend was unstyled** — the JSX is written in Tailwind utility classes but Tailwind was never
   installed (CSS bundle was 3.7 kB). **Fix:** added Tailwind v4 via `@tailwindcss/vite` (bundle now
   ~24 kB).
6. Housekeeping: `VITE_API_BASE` made configurable; `.env.example` for both `api/` and `web/`;
   `api/.gitignore` for the SQLite DB + object-storage dirs; dead imports removed (ruff clean);
   Pydantic v1 `class Config` → `ConfigDict`.

**Note:** `finauto-saas/` is not yet a git repo (`git init` it per the workspace one-repo-per-app
convention). The report step needs LibreOffice (or the `formulas` fallback) for `recalc`.
