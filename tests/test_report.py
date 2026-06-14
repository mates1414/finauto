"""Report generation: grounded context assembly + the no-fabrication guard.

The LLM is monkeypatched (an injected writer); we assert the narrative is bound
to the provided figures (workspace invariant #8).
"""

from __future__ import annotations

import pytest

from finauto.report import build_context, generate, ungrounded_figures
from finauto.report.generator import ReportContext
from finauto.schemas import StrategicReport


class FakeWriter:
    model = "fake-model"

    def __init__(self, text: str):
        self.text = text
        self.calls: list[tuple[str, str, bool]] = []

    def complete(self, system: str, user: str, *, stream: bool = True) -> str:
        self.calls.append((system, user, stream))
        return self.text


def _ctx() -> ReportContext:
    return ReportContext(
        ticker="DEMO.IS",
        name="Demo A.Ş.",
        currency="TRY",
        computed={
            "target_price": 120.0,
            "current_price": 95.5,
            "upside": 0.2563,
            "signal": "AL",
            "dcf_price": 130.0,
            "ev_ebitda_price": 110.0,
            "pe_price": 118.0,
            "ev_sales_price": None,
            "wacc": 0.31,
            "cost_of_equity": 0.42,
            "cost_of_debt": 0.29,
            "fx_price": None,
        },
        financials_latest={
            "revenue": 145_000_000_000.0,
            "ebitda": 23_500_000_000.0,
            "ebit": 17_300_000_000.0,
            "net_income": 10_400_000_000.0,
            "net_debt": 27_000_000_000.0,
        },
        gaps=["2025: capex"],
        edits=[],
        peers=["Peer A (PEERA.IS)"],
        inflation_caveat=True,
    )


def test_generate_returns_grounded_report():
    ctx = _ctx()
    md = (
        "## Thesis\nWeighted target price 120.00 vs current 95.50, upside 25.63%. "
        "Signal: AL. WACC 31.00%. Net debt (incl. leases) 27,000,000,000.\n"
        "Post-2022 TMS-29 restatement distorts nominal growth."
    )
    writer = FakeWriter(md)
    report = generate(ctx, writer=writer, stream=False)

    assert isinstance(report, StrategicReport)
    assert report.ticker == "DEMO.IS"
    assert report.model == "fake-model"
    assert "120.00" in report.markdown
    # every number in the narrative traces to the context (TMS-29 is allowed)
    assert ungrounded_figures(report.markdown, ctx) == []


def test_fabricated_figure_is_flagged():
    ctx = _ctx()
    md = "Target price 120.00, but revenue is magically 999,999,999."
    assert "999,999,999" in ungrounded_figures(md, ctx)


def test_writer_receives_system_and_grounded_data():
    ctx = _ctx()
    writer = FakeWriter("ok 120.00")
    generate(ctx, writer=writer, stream=True)

    system, user, stream = writer.calls[0]
    assert "analyst" in system.lower()
    assert "120.00" in user  # the grounded target price is in the DATA block
    assert stream is True


def test_build_context_from_financials(fin):
    computed = {"target_price": 120.0, "signal": "AL"}
    ctx = build_context(fin.with_deduped_periods(), computed, original=None)

    assert ctx.ticker == "DEMO.IS"
    assert ctx.financials_latest["revenue"] == pytest.approx(145_000_000 * 1000)
    assert ctx.financials_latest["ebit"] == pytest.approx(17_300_000 * 1000)
    # net debt incl. leases for 2025 (absolute units)
    expected_net_debt = (8_500_000 + 24_000_000 + 13_500_000 - 18_500_000) * 1000
    assert ctx.financials_latest["net_debt"] == pytest.approx(expected_net_debt)
    # gross_profit is null in every fixture period -> appears in the gap report
    assert any("gross_profit" in g for g in ctx.gaps)
