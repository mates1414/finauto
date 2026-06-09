"""Gemini extractor: native PDF input + structured output against the
CompanyFinancials pydantic schema (google-genai SDK, GEMINI_API_KEY env)."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from ..schemas import CompanyFinancials
from .base import ExtractionError
from .pdf_loader import load_pdf_bytes
from .prompts import build_extraction_prompt


class GeminiExtractor:
    def __init__(self, model: str):
        self.model = model

    def extract(self, pdf_paths: list[Path], ticker: str) -> CompanyFinancials:
        try:
            from google import genai
            from google.genai import types
        except ImportError as e:
            raise ExtractionError(
                "google-genai is not installed; run: pip install finauto[llm]"
            ) from e

        client = genai.Client()
        contents: list = [
            types.Part.from_bytes(data=load_pdf_bytes(p), mime_type="application/pdf")
            for p in pdf_paths
        ]
        contents.append(build_extraction_prompt(ticker))
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=CompanyFinancials,
        )

        last_error: Exception | None = None
        for _attempt in range(2):  # one schema-repair retry
            response = client.models.generate_content(
                model=self.model, contents=contents, config=config
            )
            fin = response.parsed
            if isinstance(fin, CompanyFinancials):
                fin.ticker = ticker
                fin.source = f"gemini:{self.model}"
                return fin
            try:
                fin = CompanyFinancials.model_validate_json(response.text or "")
                fin.ticker = ticker
                fin.source = f"gemini:{self.model}"
                return fin
            except ValidationError as e:
                last_error = e
        raise ExtractionError(f"Gemini returned no schema-valid output: {last_error}")
