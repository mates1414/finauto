"""Autonomous competitor discovery (Phase 3, A2).

Mirrors `ingestion/base.py`: a `PeerResearcher` Protocol + a `get_peer_researcher`
factory. **Add a provider by implementing the Protocol — never by branching in
callers.** Only the *search* primitive is provider-specific (Gemini Google Search
grounding vs. Claude `web_search`); everything downstream is provider-neutral.

The hallucination filter is `resolve_and_validate`: every proposed peer is checked
against live `marketdata/yahoo.snapshot`; unresolved names are dropped with a
reason. Peers therefore still resolve **per run** (workspace invariant #7 — no
hardcoded tickers/peers), and the LLM can only *suggest*, never fabricate, a peer
that survives into the model.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Callable, Optional, Protocol

from ..config import Settings
from ..schemas import PeerCandidate, PeerSuggestionSet


class PeerResearchError(Exception):
    pass


# Shared, provider-neutral instruction. Kept terse: the schema is enforced by the
# structured-output step, so this only carries domain intent + the anti-hallucination
# rule that the validation step then *enforces*.
DISCOVERY_SYSTEM = (
    "You are an equity research assistant. Propose publicly listed comparable "
    "companies for a target company: same sector, ideally the same exchange and "
    "country, similar size and business model. Return the stock ticker where you "
    "know it; NEVER invent a ticker — leave it blank if unsure. Give a one-line "
    "rationale and a 0..1 confidence for each. Prefer quality over quantity."
)


def build_discovery_prompt(
    target_name: str, *, sector: Optional[str], country: str, n: int
) -> str:
    sector_line = f" operating in {sector}" if sector else ""
    return (
        f"Find up to {n} listed peer companies for {target_name}{sector_line}, "
        f"focused on {country}. For each peer give: company name, stock ticker "
        f"(with exchange suffix, e.g. BIMAS.IS, where known), exchange, a short "
        f"rationale, and a confidence between 0 and 1. Do not invent tickers."
    )


class PeerResearcher(Protocol):
    def discover(
        self,
        target_name: str,
        *,
        sector: Optional[str] = None,
        country: str = "Türkiye",
        n: int = 5,
    ) -> PeerSuggestionSet: ...


def get_peer_researcher(settings: Settings) -> PeerResearcher:
    provider, model = settings.stage("discover")
    if provider == "gemini":
        return GeminiPeerResearcher(model)
    if provider == "claude":
        return ClaudePeerResearcher(model)
    raise ValueError(f"unknown discovery provider: {provider}")


def _parse_suggestion_json(
    raw: str, target_name: str, source: str
) -> PeerSuggestionSet:
    """Coerce a model's JSON into PeerSuggestionSet with a forgiving fallback.

    Accepts either a full PeerSuggestionSet shape or a bare list of candidates,
    so a provider that only returns the candidate array still validates.
    """
    data = json.loads(raw)
    if isinstance(data, list):
        data = {"candidates": data}
    data.setdefault("target", target_name)
    data["source"] = source
    suggestion = PeerSuggestionSet.model_validate(data)
    suggestion.target = target_name  # never trust the model for the target name
    return suggestion


class GeminiPeerResearcher:
    """Gemini with Google Search grounding, then a schema-bound structuring pass."""

    def __init__(self, model: str):
        self.model = model

    def discover(
        self,
        target_name: str,
        *,
        sector: Optional[str] = None,
        country: str = "Türkiye",
        n: int = 5,
    ) -> PeerSuggestionSet:
        try:
            from google import genai
            from google.genai import types
        except ImportError as e:
            raise PeerResearchError(
                "google-genai is not installed; run: pip install finauto[llm]"
            ) from e

        client = genai.Client()
        prompt = f"{DISCOVERY_SYSTEM}\n\n{build_discovery_prompt(target_name, sector=sector, country=country, n=n)}"

        # 1) Grounded research (Google Search) -> free text + citations.
        grounded = client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())]
            ),
        )
        research = grounded.text or ""

        # 2) Structure the research into the schema (no tools + response_schema).
        structured = client.models.generate_content(
            model=self.model,
            contents=(
                f"{DISCOVERY_SYSTEM}\n\nResearch notes for {target_name}:\n{research}\n\n"
                "Return the peer list as JSON."
            ),
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=PeerSuggestionSet,
            ),
        )
        source = f"gemini google-search {date.today().isoformat()}"
        parsed = structured.parsed
        if isinstance(parsed, PeerSuggestionSet):
            parsed.target = target_name
            parsed.source = source
            return parsed
        try:
            return _parse_suggestion_json(structured.text or "", target_name, source)
        except (json.JSONDecodeError, ValueError) as e:
            raise PeerResearchError(
                f"Gemini discovery returned no valid peer set: {e}"
            ) from e


class ClaudePeerResearcher:
    """Claude `web_search`/`web_fetch` research, then a schema-bound parse with a repair retry."""

    def __init__(self, model: str):
        self.model = model

    def discover(
        self,
        target_name: str,
        *,
        sector: Optional[str] = None,
        country: str = "Türkiye",
        n: int = 5,
    ) -> PeerSuggestionSet:
        try:
            import anthropic
        except ImportError as e:
            raise PeerResearchError(
                "anthropic is not installed; run: pip install finauto[llm]"
            ) from e

        client = anthropic.Anthropic()
        prompt = build_discovery_prompt(
            target_name, sector=sector, country=country, n=n
        )

        # 1) Server-side web search (dynamic filtering on Opus 4.8 / Sonnet 4.6),
        #    looping on pause_turn until the tool loop completes.
        messages: list[dict] = [{"role": "user", "content": prompt}]
        research = ""
        for _ in range(6):
            resp = client.messages.create(
                model=self.model,
                max_tokens=8000,
                system=DISCOVERY_SYSTEM,
                thinking={"type": "adaptive"},
                tools=[
                    {"type": "web_search_20260209", "name": "web_search"},
                    {"type": "web_fetch_20260209", "name": "web_fetch"},
                ],
                messages=messages,
            )
            research += "".join(b.text for b in resp.content if b.type == "text")
            if resp.stop_reason != "pause_turn":
                break
            messages = [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": resp.content},
            ]

        # 2) Structure into the schema with one repair retry.
        source = f"claude web_search {date.today().isoformat()}"
        last_error: Optional[str] = None
        for _ in range(2):
            structured = client.messages.parse(
                model=self.model,
                max_tokens=4000,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Research notes for peers of {target_name}:\n{research}\n\n"
                            "Extract the peer list. Do not invent tickers."
                        ),
                    }
                ],
                output_format=PeerSuggestionSet,
            )
            parsed = structured.parsed_output
            if parsed is not None:
                parsed.target = target_name
                parsed.source = source
                return parsed
            last_error = f"stop_reason={structured.stop_reason}"
        raise PeerResearchError(
            f"Claude discovery returned no schema-valid peer set: {last_error}"
        )


def _candidate_ticker(candidate: PeerCandidate, default_suffix: str) -> Optional[str]:
    """Best-effort ticker for validation; None means 'cannot validate -> drop'.

    A bare symbol with no exchange suffix gets the default suffix appended
    (e.g. ``BIMAS`` -> ``BIMAS.IS``). A candidate with no ticker at all cannot be
    validated against live data and is dropped — that is the hallucination filter.
    """
    if not candidate.ticker:
        return None
    t = candidate.ticker.strip().upper()
    if not t:
        return None
    if "." not in t and default_suffix:
        t = f"{t}{default_suffix}"
    return t


def resolve_and_validate(
    suggestion: PeerSuggestionSet,
    *,
    snapshot_fn: Optional[Callable[[str], object]] = None,
    default_suffix: str = ".IS",
) -> PeerSuggestionSet:
    """Validate every candidate against live market data (provider-independent).

    For each candidate: resolve a ticker, fetch a Yahoo snapshot, and keep it only
    if the snapshot carries a price or market cap. Survivors are marked
    ``resolved`` with their ``market_cap``; everything else is moved to ``dropped``
    with a reason. This runs regardless of which provider did the searching.
    """
    if snapshot_fn is None:
        from .yahoo import (
            snapshot as snapshot_fn,
        )  # lazy: avoid importing yfinance at module load

    kept: list[PeerCandidate] = []
    dropped: list[str] = list(suggestion.dropped)
    seen: set[str] = set()
    for cand in suggestion.candidates:
        ticker = _candidate_ticker(cand, default_suffix)
        if ticker is None:
            dropped.append(f"{cand.name}: no ticker to validate")
            continue
        if ticker in seen:
            continue
        seen.add(ticker)
        try:
            snap = snapshot_fn(ticker)
        except Exception as e:  # network / lookup failure -> treat as unresolved
            dropped.append(f"{cand.name} ({ticker}): snapshot failed ({e})")
            continue
        price = getattr(snap, "price", None)
        market_cap = getattr(snap, "market_cap", None)
        if price is None and market_cap is None:
            dropped.append(f"{cand.name} ({ticker}): no live price/market cap")
            continue
        kept.append(
            cand.model_copy(
                update={"ticker": ticker, "resolved": True, "market_cap": market_cap}
            )
        )

    return PeerSuggestionSet(
        target=suggestion.target,
        candidates=kept,
        dropped=dropped,
        source=suggestion.source,
    )
