"""Gemini extractor: native PDF input + structured output against the
CompanyFinancials pydantic schema (google-genai SDK, GEMINI_API_KEY env)."""

from __future__ import annotations

import time
from pathlib import Path

from pydantic import ValidationError

from ..schemas import CompanyFinancials
from .base import ExtractionError
from .pdf_loader import load_pdf_bytes
from .prompts import build_extraction_prompt

_MAX_ATTEMPTS = 5  # total tries across transient API errors + schema repair


class GeminiExtractor:
    def __init__(self, model: str):
        self.model = model

    def extract(self, pdf_paths: list[Path], ticker: str) -> CompanyFinancials:
        try:
            from google import genai
            from google.genai import errors, types
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
        for attempt in range(_MAX_ATTEMPTS):
            try:
                response = client.models.generate_content(
                    model=self.model, contents=contents, config=config
                )
            except errors.ServerError as e:  # 5xx — transient overload (e.g. 503)
                last_error = e
                self._backoff(attempt)
                continue
            except errors.ClientError as e:  # 429 rate limit is also transient
                last_error = e
                if getattr(e, "code", None) == 429:
                    self._backoff(attempt)
                    continue
                raise ExtractionError(f"Gemini request rejected: {e}") from e

            fin = self._parse(response, ticker)
            if fin is not None:
                return fin
            last_error = ValueError("response did not match the financials schema")

        raise ExtractionError(
            f"Gemini extraction failed after {_MAX_ATTEMPTS} attempts: {last_error}. "
            "If this is a 503/UNAVAILABLE the model is temporarily overloaded — "
            "wait a minute and retry, or set FINAUTO_GEMINI_MODEL=gemini-2.5-pro."
        )

    @staticmethod
    def _backoff(attempt: int) -> None:
        time.sleep(min(2**attempt * 5, 60))  # 5s, 10s, 20s, 40s, 60s

    @staticmethod
    def _parse(response, ticker: str) -> CompanyFinancials | None:
        fin = response.parsed
        if not isinstance(fin, CompanyFinancials):
            try:
                fin = CompanyFinancials.model_validate_json(response.text or "")
            except ValidationError:
                return None
        fin.ticker = ticker
        fin.source = "gemini"
        return fin
