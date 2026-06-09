"""Claude extractor: PDF document blocks + structured output via
client.messages.parse() against the CompanyFinancials pydantic schema
(anthropic SDK, ANTHROPIC_API_KEY env)."""

from __future__ import annotations

import base64
from pathlib import Path

from ..schemas import CompanyFinancials
from .base import ExtractionError
from .pdf_loader import load_pdf_bytes
from .prompts import build_extraction_prompt


class ClaudeExtractor:
    def __init__(self, model: str):
        self.model = model

    def extract(self, pdf_paths: list[Path], ticker: str) -> CompanyFinancials:
        try:
            import anthropic
        except ImportError as e:
            raise ExtractionError(
                "anthropic is not installed; run: pip install finauto[llm]"
            ) from e

        client = anthropic.Anthropic()
        content: list[dict] = [
            {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": base64.standard_b64encode(load_pdf_bytes(p)).decode("utf-8"),
                },
            }
            for p in pdf_paths
        ]
        content.append({"type": "text", "text": build_extraction_prompt(ticker)})

        last_error: str | None = None
        for _attempt in range(2):  # one schema-repair retry
            response = client.messages.parse(
                model=self.model,
                max_tokens=16000,
                thinking={"type": "adaptive"},
                messages=[{"role": "user", "content": content}],
                output_format=CompanyFinancials,
            )
            fin = response.parsed_output
            if fin is not None:
                fin.ticker = ticker
                fin.source = f"claude:{self.model}"
                return fin
            last_error = f"stop_reason={response.stop_reason}"
        raise ExtractionError(f"Claude returned no schema-valid output: {last_error}")
