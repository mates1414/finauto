"""Tests for the OpenAI-compatible extractor and per-stage extract routing.

No network or `openai` SDK needed: the client is injected, and `load_pdf_text`
is monkeypatched so no real PDF is parsed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from finauto.config import Settings
from finauto.ingestion import openai_compat
from finauto.ingestion.base import ExtractionError, get_extractor
from finauto.ingestion.openai_compat import OpenAICompatExtractor
from finauto.schemas import (
    CompanyFinancials,
    FiscalYearData,
    IncomeStatement,
)


# --- a minimal fake of the openai client surface used by the extractor --------
class _FakeCompletions:
    def __init__(self, content: str):
        self._content = content
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        msg = type("M", (), {"content": self._content})
        choice = type("C", (), {"message": msg})
        return type("R", (), {"choices": [choice]})


class _FakeClient:
    def __init__(self, content: str):
        self.chat = type("Chat", (), {"completions": _FakeCompletions(content)})


def _valid_payload() -> str:
    return CompanyFinancials(
        ticker="PLACEHOLDER",
        name="Mock Co",
        units="thousands",
        periods=[
            FiscalYearData(
                year=2023,
                income_statement=IncomeStatement(revenue=100.0, net_income=8.0),
            )
        ],
    ).model_dump_json()


def test_extract_parses_and_overrides_identity(monkeypatch):
    monkeypatch.setattr(openai_compat, "load_pdf_text", lambda p, **k: "Hasılat 100")
    client = _FakeClient(_valid_payload())
    ex = OpenAICompatExtractor(
        "deepseek-chat", base_url="https://api.deepseek.com", client=client
    )

    fin = ex.extract([Path("dummy.pdf")], "BIMAS.IS")

    assert fin.ticker == "BIMAS.IS"  # caller ticker wins over the model's value
    assert fin.source == "openai:deepseek-chat"
    assert fin.periods[0].income_statement.revenue == 100.0
    # JSON mode was requested
    assert client.chat.completions.calls[0]["response_format"] == {"type": "json_object"}


def test_extract_rejects_schema_invalid_output(monkeypatch):
    monkeypatch.setattr(openai_compat, "load_pdf_text", lambda p, **k: "some text")
    # missing the required `ticker` field -> never validates
    ex = OpenAICompatExtractor("m", client=_FakeClient('{"name": "x"}'))
    with pytest.raises(ExtractionError):
        ex.extract([Path("d.pdf")], "T")


def test_extract_empty_text_is_clear_error(monkeypatch):
    monkeypatch.setattr(openai_compat, "load_pdf_text", lambda p, **k: "   ")
    ex = OpenAICompatExtractor("m", client=_FakeClient("{}"))
    with pytest.raises(ExtractionError, match="text-only"):
        ex.extract([Path("d.pdf")], "T")


def test_get_extractor_routes_openai():
    s = Settings(
        llm_provider="openai",
        openai_model="deepseek-chat",
        openai_base_url="https://api.deepseek.com",
    )
    ex = get_extractor(s)
    assert isinstance(ex, OpenAICompatExtractor)
    assert ex.model == "deepseek-chat"
    assert ex.base_url == "https://api.deepseek.com"


def test_get_extractor_respects_extract_provider_override():
    # Global default stays gemini, but the extract stage is pinned to openai.
    # This is the per-stage routing that was previously dead config.
    s = Settings(llm_provider="gemini", extract_provider="openai")
    assert isinstance(get_extractor(s), OpenAICompatExtractor)
