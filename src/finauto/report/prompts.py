"""System prompt + grounded-context formatting for the report writer.

The narrative must only cite figures present in the provided context (workspace
invariant #8 — validate/ground, never fabricate). `format_context` returns both
the human-readable context block sent to the model *and* the set of numbers the
narrative is allowed to mention, which the grounding check enforces.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .generator import ReportContext

SYSTEM_PROMPT = """\
You are an equity research analyst writing a concise strategic valuation memo.

Strict rules:
- Cite ONLY figures that appear in the DATA block below. Never invent a number,
  growth rate, multiple, or price. If something is not in the data, say it is not
  available rather than estimating it.
- If the data is flagged as inflation-restated (Turkish TMS-29 / IAS-29), state
  that nominal TRY growth and terminal value are distorted and should be
  cross-checked in hard currency. Do not silently trust nominal growth.
- The signal (AL = buy, TUT = hold, SAT = sell) and the target price come from
  the model; explain them, do not re-derive a different number.

Structure the memo with these sections, as Markdown:
1. Investment thesis (2-4 sentences).
2. DCF valuation — what the WACC and target price imply.
3. Relative valuation — what the peer multiples imply.
4. Risks & caveats — include the inflation/FX caveat and any data gaps listed.
5. Recommendation — restate the AL/TUT/SAT signal and the upside, with rationale.

Be specific and grounded; prefer short paragraphs over filler.
"""


def _fmt(value, *, pct: bool = False, money: bool = False) -> str:
    if value is None:
        return "n/a"
    if pct:
        return f"{value * 100:.2f}%"
    if money:
        return f"{value:,.2f}"
    return f"{value:,.2f}"


def format_context(ctx: "ReportContext") -> str:
    """Render the grounded DATA block sent to the model."""
    c = ctx.computed
    lines: list[str] = []
    lines.append(
        f"Company: {ctx.name or ctx.ticker} ({ctx.ticker}); currency {ctx.currency}."
    )
    lines.append("")
    lines.append("Valuation outputs:")
    lines.append(f"- Weighted target price: {_fmt(c.get('target_price'), money=True)}")
    lines.append(f"- Current price: {_fmt(c.get('current_price'), money=True)}")
    lines.append(f"- Upside vs current: {_fmt(c.get('upside'), pct=True)}")
    signal = c.get("signal")
    lines.append(f"- Signal: {signal if isinstance(signal, str) else 'n/a'}")
    lines.append(f"- DCF implied price: {_fmt(c.get('dcf_price'), money=True)}")
    lines.append(
        f"- EV/EBITDA implied price: {_fmt(c.get('ev_ebitda_price'), money=True)}"
    )
    lines.append(f"- P/E implied price: {_fmt(c.get('pe_price'), money=True)}")
    lines.append(
        f"- EV/Sales implied price: {_fmt(c.get('ev_sales_price'), money=True)}"
    )
    lines.append(f"- WACC: {_fmt(c.get('wacc'), pct=True)}")
    lines.append(f"- Cost of equity: {_fmt(c.get('cost_of_equity'), pct=True)}")
    lines.append(f"- Cost of debt: {_fmt(c.get('cost_of_debt'), pct=True)}")
    fx = c.get("fx_price")
    if fx is not None:
        lines.append(f"- Target price in hard currency: {_fmt(fx, money=True)}")

    lines.append("")
    lines.append("Latest-year financials (absolute currency units):")
    for label, key in (
        ("Revenue", "revenue"),
        ("EBITDA", "ebitda"),
        ("EBIT", "ebit"),
        ("Net income", "net_income"),
        ("Net debt (incl. leases)", "net_debt"),
    ):
        lines.append(f"- {label}: {_fmt(ctx.financials_latest.get(key), money=True)}")

    if ctx.peers:
        lines.append("")
        lines.append("Peer set: " + ", ".join(ctx.peers))

    if ctx.edits:
        lines.append("")
        lines.append("User corrections applied to the model:")
        for e in ctx.edits[:40]:
            lines.append(
                f"- {e.path}: {_fmt(e.old, money=True)} -> {_fmt(e.new, money=True)}"
            )

    if ctx.gaps:
        lines.append("")
        lines.append("Data gaps (left blank in the model):")
        for g in ctx.gaps[:40]:
            lines.append(f"- {g}")

    if ctx.inflation_caveat:
        lines.append("")
        lines.append(
            "NOTE: Post-2022 BIST financials are TMS-29/IAS-29 inflation-restated; "
            "nominal TRY growth and terminal value are distorted."
        )

    return "\n".join(lines)


def build_user_prompt(ctx: "ReportContext") -> str:
    return (
        f"Write the strategic valuation memo for {ctx.name or ctx.ticker}.\n\n"
        f"DATA:\n{format_context(ctx)}"
    )
