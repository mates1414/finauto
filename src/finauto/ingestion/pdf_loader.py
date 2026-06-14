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


def _validate_pdf_header(path: Path) -> None:
    header = path.read_bytes()[:5]
    if header[:4] != b"%PDF":
        raise ValueError(
            f"{path} is not a valid PDF (header={header!r}, expected b'%PDF-'). "
            "The file is likely corrupted or saved in the wrong format — "
            "re-download the report PDF from KAP and try again."
        )


def load_pdf_bytes(path: Path, max_pages: int = MAX_PAGES) -> bytes:
    _validate_pdf_header(path)
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


def load_pdf_text(path: Path, max_pages: int = MAX_PAGES) -> str:
    """Extract text from a PDF's financial-statement pages (for text-only LLMs).

    Mirrors ``load_pdf_bytes``' page selection (keyword pages + neighbours) but
    returns concatenated page text instead of PDF bytes, for OpenAI-compatible
    providers that cannot read PDFs natively. Returns ``""`` when the PDF has no
    extractable text (e.g. scanned/image-only) so the caller can fail clearly.
    """
    _validate_pdf_header(path)
    with pdfplumber.open(path) as pdf:
        pages = pdf.pages
        n = len(pages)
        texts = [page.extract_text() or "" for page in pages]

    if n <= max_pages:
        kept = texts
    else:
        keep = [i for i, t in enumerate(texts) if any(k in t.lower() for k in _KEYWORDS)]
        if not keep:
            keep = list(range(max_pages))
        # include neighbours: statement tables often continue onto the next page
        expanded = sorted({j for i in keep for j in (i - 1, i, i + 1) if 0 <= j < n})
        kept = [texts[i] for i in expanded[:max_pages]]

    return "\n\n".join(t for t in kept if t.strip()).strip()
