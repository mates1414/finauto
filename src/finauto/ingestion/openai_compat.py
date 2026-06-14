"""OpenAI-compatible extractor: works with any Chat Completions endpoint
(DeepSeek, OpenRouter, Together, OpenAI, local servers) via base_url + API key.

These providers are **text-only**, so the PDF is converted to text first
(pdfplumber) — lower fidelity than native-PDF Gemini/Claude, but much cheaper.
Text PDFs only; scanned/image-only PDFs are rejected with a clear error.

Output is bound to the CompanyFinancials schema via JSON mode and validated with
a repair retry, matching the other providers (workspace invariant #8)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from pydantic import ValidationError

from ..schemas import CompanyFinancials
from .base import ExtractionError
from .pdf_loader import load_pdf_text
from .prompts import build_extraction_prompt

_MAX_ATTEMPTS = 4  # transient API errors + schema-repair retries
_TRANSIENT_CODES = {429, 500, 502, 503, 504}
_TRANSIENT_NAMES = {
    "RateLimitError",
    "APITimeoutError",
    "APIConnectionError",
    "InternalServerError",
}


def _is_transient(e: Exception) -> bool:
    if getattr(e, "status_code", None) in _TRANSIENT_CODES:
        return True
    return type(e).__name__ in _TRANSIENT_NAMES


class OpenAICompatExtractor:
    def __init__(self, model: str, base_url: Optional[str] = None, client=None):
        self.model = model
        self.base_url = base_url
        self._client = client  # injectable for tests; lazily created otherwise

    def _make_client(self):
        try:
            from openai import OpenAI
        except ImportError as e:
            raise ExtractionError(
                "openai is not installed; run: pip install finauto[llm]"
            ) from e
        # The SDK reads OPENAI_API_KEY from the environment; base_url targets the vendor.
        return OpenAI(base_url=self.base_url) if self.base_url else OpenAI()

    def extract(self, pdf_paths: list[Path], ticker: str) -> CompanyFinancials:
        client = self._client or self._make_client()

        raw_texts = [load_pdf_text(p) for p in pdf_paths]
        if not any(t.strip() for t in raw_texts):
            raise ExtractionError(
                "No extractable text found in the PDF(s). OpenAI-compatible providers "
                "are text-only; scanned/image-only PDFs are not supported — use the "
                "gemini or claude provider for those."
            )
        text = "\n\n".join(
            f"--- DOCUMENT {i + 1}: {p.name} ---\n{t}"
            for i, (p, t) in enumerate(zip(pdf_paths, raw_texts))
        )

        system = (
            "You are a financial data extraction engine. Respond with a single JSON "
            "object only — no prose, no markdown code fences."
        )
        user = (
            build_extraction_prompt(ticker)
            + "\n\nReturn ONLY a JSON object conforming to this JSON Schema:\n"
            + json.dumps(CompanyFinancials.model_json_schema())
            + "\n\n=== EXTRACTED REPORT TEXT ===\n"
            + text
        )

        last_error: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                resp = client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0,
                )
            except Exception as e:  # noqa: BLE001 - normalize SDK/network errors
                last_error = e
                if _is_transient(e) and attempt < _MAX_ATTEMPTS - 1:
                    time.sleep(min(2**attempt * 5, 60))
                    continue
                raise ExtractionError(
                    f"OpenAI-compatible request failed: {e}"
                ) from e

            content = resp.choices[0].message.content or ""
            fin = self._parse(content, ticker)
            if fin is not None:
                return fin
            last_error = ValueError("response did not match the financials schema")

        raise ExtractionError(
            f"OpenAI-compatible extraction failed after {_MAX_ATTEMPTS} attempts: "
            f"{last_error}."
        )

    def _parse(self, content: str, ticker: str) -> CompanyFinancials | None:
        try:
            fin = CompanyFinancials.model_validate_json(content)
        except ValidationError:
            return None
        fin.ticker = ticker
        fin.source = f"openai:{self.model}"
        return fin
