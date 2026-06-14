"""Peer discovery validation: the hallucination filter and schema parsing.

No live network/LLM — `resolve_and_validate` takes an injected snapshot function,
and structured parsing is exercised against a saved response shape.
"""

from __future__ import annotations

from finauto.marketdata.web_research import resolve_and_validate
from finauto.schemas import PeerCandidate, PeerSuggestionSet


class FakeSnap:
    def __init__(self, price=None, market_cap=None):
        self.price = price
        self.market_cap = market_cap


def test_resolve_and_validate_filters_and_sorts():
    suggestion = PeerSuggestionSet(
        target="DEMO.IS",
        candidates=[
            PeerCandidate(name="Real Co", ticker="REAL.IS", confidence=0.9),
            PeerCandidate(
                name="Bare Symbol", ticker="BARE", confidence=0.5
            ),  # -> BARE.IS
            PeerCandidate(
                name="Ghost Co", ticker="GHOST.IS", confidence=0.4
            ),  # no live data
            PeerCandidate(
                name="No Ticker Co", ticker=None, confidence=0.3
            ),  # cannot validate
        ],
    )
    snaps = {
        "REAL.IS": FakeSnap(price=10.0, market_cap=1000.0),
        "BARE.IS": FakeSnap(price=5.0, market_cap=500.0),
        "GHOST.IS": FakeSnap(price=None, market_cap=None),
    }
    out = resolve_and_validate(
        suggestion, snapshot_fn=lambda t: snaps.get(t, FakeSnap())
    )

    # Bare symbol got the .IS suffix and resolved; ghost + no-ticker were dropped.
    assert out.tickers() == ["REAL.IS", "BARE.IS"]  # sorted by market cap desc
    dropped = " ".join(out.dropped)
    assert "Ghost Co" in dropped and "No Ticker Co" in dropped
    assert all(c.resolved and c.market_cap is not None for c in out.resolved())


def test_snapshot_exception_drops_candidate():
    suggestion = PeerSuggestionSet(
        target="X", candidates=[PeerCandidate(name="Boom", ticker="BOOM.IS")]
    )

    def boom(_ticker):
        raise RuntimeError("network down")

    out = resolve_and_validate(suggestion, snapshot_fn=boom)
    assert out.tickers() == []
    assert any("Boom" in d and "network down" in d for d in out.dropped)


def test_parse_structured_response_fixture():
    raw = {
        "target": "DEMO.IS",
        "candidates": [
            {
                "name": "Peer A",
                "ticker": "PEERA.IS",
                "exchange": "BIST",
                "rationale": "same sector and exchange",
                "confidence": 0.8,
            }
        ],
        "dropped": [],
        "source": "claude web_search 2026-06-13",
    }
    s = PeerSuggestionSet.model_validate(raw)
    assert s.candidates[0].ticker == "PEERA.IS"
    assert s.candidates[0].confidence == 0.8
    # nothing is resolved until validation runs
    assert s.tickers() == []
