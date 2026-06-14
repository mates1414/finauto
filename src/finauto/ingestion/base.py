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
    # Resolve via the per-stage router so FINAUTO_EXTRACT_PROVIDER/_MODEL take
    # effect; unset values fall back to the global llm_provider + default model.
    provider, model = settings.stage("extract")
    if provider == "gemini":
        from .gemini import GeminiExtractor

        return GeminiExtractor(model)
    if provider == "claude":
        from .claude import ClaudeExtractor

        return ClaudeExtractor(model)
    if provider == "openai":
        from .openai_compat import OpenAICompatExtractor

        return OpenAICompatExtractor(model, base_url=settings.openai_base_url)
    raise ValueError(f"unknown LLM provider: {provider}")
