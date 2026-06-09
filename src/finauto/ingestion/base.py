"""Pluggable LLM extraction interface. Providers are imported lazily so the
core pipeline (build from JSON) never requires the LLM SDKs."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ..config import Settings
from ..schemas import CompanyFinancials


class ExtractionError(Exception):
    pass


class Extractor(Protocol):
    def extract(self, pdf_paths: list[Path], ticker: str) -> CompanyFinancials: ...


def get_extractor(settings: Settings) -> Extractor:
    if settings.llm_provider == "gemini":
        from .gemini import GeminiExtractor

        return GeminiExtractor(settings.gemini_model)
    if settings.llm_provider == "claude":
        from .claude import ClaudeExtractor

        return ClaudeExtractor(settings.claude_model)
    raise ValueError(f"unknown LLM provider: {settings.llm_provider}")
