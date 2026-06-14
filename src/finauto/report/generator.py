"""Report writer: a pluggable `ReportWriter` Protocol + `get_report_writer`
factory (Gemini / Claude / others). Report writing is plain generation, so it is
fully provider-neutral — add a provider by implementing the Protocol.

`generate` assembles a grounded context block from the recalculated workbook's
computed outputs, the latest financials, the gap report, and the user's edit
diff, then streams the narrative. `ungrounded_figures` is the grounding check
(workspace invariant #8): every number the narrative mentions must trace back to
the provided context.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol

from ..config import Settings, get_settings
from ..schemas import (
    CompanyFinancials,
    EditNote,
    MarketData,
    Number,
    StrategicReport,
)
from .prompts import SYSTEM_PROMPT, build_user_prompt, format_context


@dataclass
class ReportContext:
    ticker: str
    name: Optional[str]
    currency: str
    computed: dict[str, object] = field(default_factory=dict)
    financials_latest: dict[str, Number] = field(default_factory=dict)
    gaps: list[str] = field(default_factory=list)
    edits: list[EditNote] = field(default_factory=list)
    peers: list[str] = field(default_factory=list)
    inflation_caveat: bool = True


def _net_debt(bs) -> Number:
    parts = [
        bs.short_term_debt,
        bs.long_term_debt,
        bs.lease_liabilities,
        bs.cash_and_equivalents,
    ]
    if all(p is None for p in parts):
        return None
    return (
        (bs.short_term_debt or 0.0)
        + (bs.long_term_debt or 0.0)
        + (bs.lease_liabilities or 0.0)
        - (bs.cash_and_equivalents or 0.0)
    )


def build_context(
    financials: CompanyFinancials,
    computed: dict[str, object],
    *,
    original: Optional[CompanyFinancials] = None,
    market: Optional[MarketData] = None,
    gaps: Optional[list[str]] = None,
    inflation_caveat: bool = True,
    ticker: Optional[str] = None,
    name: Optional[str] = None,
) -> ReportContext:
    """Assemble the grounded context for the report from read-back inputs."""
    from ..engine.readback import diff_inputs
    from ..validation.sanity import financials_gap_report, reconcile_financials

    norm = financials.normalized()
    latest = norm.sorted_periods()[-1] if norm.periods else None
    financials_latest: dict[str, Number] = {}
    if latest is not None:
        inc, bs = latest.income_statement, latest.balance_sheet
        ebit = inc.ebit
        if (
            ebit is None
            and inc.ebitda is not None
            and inc.depreciation_amortization is not None
        ):
            ebit = inc.ebitda - inc.depreciation_amortization
        financials_latest = {
            "revenue": inc.revenue,
            "ebitda": inc.ebitda,
            "ebit": ebit,
            "net_income": inc.net_income,
            "net_debt": _net_debt(bs),
        }

    peers: list[str] = []
    if market is not None:
        for p in market.peers:
            peers.append(f"{p.name} ({p.ticker})" if p.name else p.ticker)

    # Diff against the reconciled original — the same baseline the builder wrote —
    # so the edit notes capture genuine user corrections, not the engine's own
    # arithmetic fills (e.g. a blank EBITDA derived from gross profit - SG&A).
    edits: list[EditNote] = []
    if original is not None:
        baseline, _notes = reconcile_financials(original)
        edits = diff_inputs(baseline, financials)

    return ReportContext(
        ticker=ticker or financials.ticker,
        name=name or financials.name,
        currency=financials.currency,
        computed=computed,
        financials_latest=financials_latest,
        gaps=gaps if gaps is not None else financials_gap_report(financials),
        edits=edits,
        peers=peers,
        inflation_caveat=inflation_caveat,
    )


class ReportWriter(Protocol):
    model: str

    def complete(self, system: str, user: str, *, stream: bool = True) -> str: ...


def get_report_writer(settings: Settings) -> ReportWriter:
    provider, model = settings.stage("report")
    if provider == "claude":
        return ClaudeReportWriter(model)
    if provider == "gemini":
        return GeminiReportWriter(model)
    raise ValueError(f"unknown report provider: {provider}")


class ClaudeReportWriter:
    def __init__(self, model: str):
        self.model = model

    def complete(self, system: str, user: str, *, stream: bool = True) -> str:
        import anthropic

        client = anthropic.Anthropic()
        kwargs = dict(
            model=self.model,
            max_tokens=8000,
            system=system,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": user}],
        )
        if stream:
            # Stream to avoid HTTP timeouts on long, minutes-scale generations.
            with client.messages.stream(**kwargs) as s:
                msg = s.get_final_message()
        else:
            msg = client.messages.create(**kwargs)
        return "".join(b.text for b in msg.content if b.type == "text")


class GeminiReportWriter:
    def __init__(self, model: str):
        self.model = model

    def complete(self, system: str, user: str, *, stream: bool = True) -> str:
        from google import genai
        from google.genai import types

        client = genai.Client()
        config = types.GenerateContentConfig(system_instruction=system)
        if stream:
            chunks = client.models.generate_content_stream(
                model=self.model, contents=user, config=config
            )
            return "".join(c.text or "" for c in chunks)
        resp = client.models.generate_content(
            model=self.model, contents=user, config=config
        )
        return resp.text or ""


def generate(
    ctx: ReportContext,
    settings: Optional[Settings] = None,
    *,
    writer: Optional[ReportWriter] = None,
    stream: bool = True,
) -> StrategicReport:
    """Generate the grounded strategic report. `writer` is injectable for tests."""
    if writer is None:
        writer = get_report_writer(settings or get_settings())
    markdown = writer.complete(SYSTEM_PROMPT, build_user_prompt(ctx), stream=stream)
    grounded = [
        ln[2:] for ln in format_context(ctx).splitlines() if ln.startswith("- ")
    ]
    return StrategicReport(
        ticker=ctx.ticker,
        markdown=markdown,
        grounded_figures=grounded,
        model=getattr(writer, "model", None),
    )


# --- Grounding check (workspace invariant #8) ---------------------------------

# Numbers not preceded by a word char, hyphen, or dot (so identifiers like
# "TMS-29" or "v1.2" are not treated as financial figures). A trailing decimal
# point is only consumed when digits follow, so sentence punctuation is excluded.
_NUM_RE = re.compile(r"(?<![\w\-.])-?\d[\d,]*(?:\.\d+)?")
# Accounting-standard references that legitimately appear as bare numbers.
_STRUCTURAL_STANDARDS = {16.0, 29.0}


def allowed_figures(ctx: ReportContext) -> set[float]:
    """The set of numbers (rounded, with %/fraction variants) the report may cite."""
    raw: list[float] = []
    for v in ctx.computed.values():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            raw.append(float(v))
    for v in ctx.financials_latest.values():
        if isinstance(v, (int, float)):
            raw.append(float(v))
    for e in ctx.edits:
        for v in (e.old, e.new):
            if isinstance(v, (int, float)):
                raw.append(float(v))
    allowed: set[float] = set()
    for x in raw:
        for variant in (x, x * 100, x / 100):
            allowed.add(round(variant, 2))
            allowed.add(float(round(variant)))
    return allowed


def ungrounded_figures(markdown: str, ctx: ReportContext) -> list[str]:
    """Number tokens in the narrative that do not trace to the context.

    Heuristic: ignores years (1900-2100), small structural integers (0-12,
    list/section numbers), and accounting-standard references (IFRS 16, TMS-29).
    Everything else must match a context figure (rounded, %/fraction tolerant).
    """
    allowed = allowed_figures(ctx)
    out: list[str] = []
    for tok in _NUM_RE.findall(markdown):
        norm = tok.replace(",", "")
        try:
            f = float(norm)
        except ValueError:
            continue
        r2, ri = round(f, 2), float(round(f))
        if 1900.0 <= f <= 2100.0 and f == ri:  # year
            continue
        if 0.0 <= f <= 12.0 and f == ri:  # structural small int
            continue
        if f in _STRUCTURAL_STANDARDS:
            continue
        if r2 in allowed or ri in allowed:
            continue
        out.append(tok)
    return out


def assert_grounded(report: StrategicReport, ctx: ReportContext) -> list[str]:
    """Convenience for Phase D / CLI: return any ungrounded figures in the report."""
    return ungrounded_figures(report.markdown, ctx)


# Type alias kept for callers that want to stream tokens to a sink later.
TokenSink = Callable[[str], None]
