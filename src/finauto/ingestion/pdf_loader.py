"""PDF pre-processing: KAP annual reports can run hundreds of pages, while the
financial statements live on a handful. When a PDF exceeds the page budget we
keep only pages whose text matches statement keywords (plus neighbours)."""

from __future__ import annotations

import io
from pathlib import Path

import pdfplumber
from pypdf import PdfReader, PdfWriter

MAX_PAGES = 80

_KEYWORDS = (
    "finansal durum tablosu",
    "kar veya zarar",
    "kâr veya zarar",
    "nakit akış",
    "bilanço",
    "gelir tablosu",
    "özkaynak değişim",
    "balance sheet",
    "income statement",
    "statement of cash flows",
    "statement of financial position",
)


def load_pdf_bytes(path: Path, max_pages: int = MAX_PAGES) -> bytes:
    reader = PdfReader(str(path))
    n = len(reader.pages)
    if n <= max_pages:
        return path.read_bytes()

    keep: list[int] = []
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = (page.extract_text() or "").lower()
            if any(k in text for k in _KEYWORDS):
                keep.append(i)
    if not keep:
        keep = list(range(max_pages))

    # include neighbours: statement tables often continue onto the next page
    expanded = sorted({j for i in keep for j in (i - 1, i, i + 1) if 0 <= j < n})
    expanded = expanded[:max_pages]

    writer = PdfWriter()
    for i in expanded:
        writer.add_page(reader.pages[i])
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()
