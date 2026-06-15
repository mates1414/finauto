"""KAP (Kamuyu Aydınlatma Platformu) statement source.

KAP is the official Turkish public-disclosure platform; every BIST company files
its financial statements there. Two public endpoints are enough to fetch them:

  1. resolve ticker -> company OID
     GET /tr/api/member/filter/{code}
         -> [{"companyCode": "1107", "mkkMemberOid": "<hex>",
              "title": "TÜRK HAVA YOLLARI A.O.", "permaLink": "..."}]

  2. download the financial-statement bundle for a year
     GET /tr/api/home-financial/download-file/{mkkMemberOid}/{year}/{type}
         -> a ZIP archive of .xls (HTML-table) statement files.

Network is the only side effect and is isolated behind ``KapClient`` (inject a
session in tests — no live calls). The ``type`` segment is the consolidation flag
KAP's own UI uses; "T" is the default that works for standard filings.

Caveat (workspace invariant #5): post-2022 BIST statements are TMS-29/IAS-29
inflation-restated — flag this downstream; nominal TRY growth is distorted.
"""

from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Optional
from urllib.parse import quote

import requests

from .base import SourceError

_ZIP_MAGIC = b"PK"  # ZIP local-file / end-of-archive headers both start with "PK"

# Turkish month names appearing in KAP report titles, ranked by recency within a
# year. The December ("Aralık") filing is the annual statement — it carries
# full-year figures plus prior-year comparatives, which is what a valuation wants.
_TR_MONTH_RANK: dict[str, int] = {
    "ocak": 1,
    "subat": 2,
    "mart": 3,
    "nisan": 4,
    "mayis": 5,
    "haziran": 6,
    "temmuz": 7,
    "agustos": 8,
    "eylul": 9,
    "ekim": 10,
    "kasim": 11,
    "aralik": 12,
}


def kap_code(ticker: str) -> str:
    """Map a finauto ticker to KAP's bare code: ``THYAO.IS`` -> ``THYAO``."""
    return ticker.split(".", 1)[0].strip().upper()


# Turkish I-variants that NFKD does not fold to ASCII "i": the dotless "ı"
# (U+0131, no decomposition) and the dotted "İ" (whose combining dot survives a
# naive lower()). Map them explicitly; NFKD handles ş/ğ/ç/ö/ü.
_TR_FOLD = str.maketrans({"ı": "i", "İ": "i", "I": "i"})


def _ascii_fold(text: str) -> str:
    """Lower-case and drop diacritics so Turkish casing folds predictably.

    Without this, ``"Aralık"`` keeps its dotless "ı" (rank lookup misses) and
    ``"İng"`` keeps a combining dot — both break naive substring matching.
    """
    decomposed = unicodedata.normalize("NFKD", text.translate(_TR_FOLD))
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def _is_english(name: str) -> bool:
    """KAP English editions carry an "İng"/"İng."/"İngilizce" marker in the title."""
    folded = _ascii_fold(name)
    return re.search(r"\bing\b|ing\.|ingilizce", folded) is not None


def _period_rank(name: str) -> int:
    """Highest Turkish-month rank found in a filename (0 if none recognised)."""
    folded = _ascii_fold(name)
    return max(
        (rank for token, rank in _TR_MONTH_RANK.items() if token in folded), default=0
    )


def select_statement_pdfs(
    paths: list[Path],
    *,
    language: Literal["tr", "en"] = "tr",
    latest_only: bool = True,
) -> list[Path]:
    """Pick the statement PDF(s) to extract from a KAP bundle.

    The bundle mixes ``.xls`` tables with TR + EN PDFs for every interim period.
    Defaults: Turkish, single most-recent period (the annual/December filing).
    Falls back to file size when no month is recognised, and never returns empty
    by language filtering alone (if only the other language exists, it is kept).
    """
    pdfs = [p for p in paths if p.suffix.lower() == ".pdf"]
    if not pdfs:
        return []
    if language == "en":
        pdfs = [p for p in pdfs if _is_english(p.name)] or pdfs
    else:
        pdfs = [p for p in pdfs if not _is_english(p.name)] or pdfs
    if not latest_only:
        return pdfs
    # Prefer the latest period; break ties by size (the annual report is largest).
    ranked = sorted(pdfs, key=lambda p: (_period_rank(p.name), p.stat().st_size))
    return [ranked[-1]]


@dataclass(frozen=True)
class KapMember:
    oid: str
    company_code: str
    title: str


class KapClient:
    """Thin HTTP client over KAP's public JSON/file endpoints."""

    BASE_URL = "https://www.kap.org.tr/tr/api"
    # KAP serves a SPA; a browser-ish UA avoids being treated as an unknown bot.
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        "Accept": "application/json, */*",
    }

    def __init__(
        self,
        *,
        session: Optional[requests.Session] = None,
        timeout: float = 30.0,
    ) -> None:
        self._session = session or requests.Session()
        self._timeout = timeout

    def resolve_member(self, ticker: str) -> KapMember:
        """Look up the KAP company OID for a ticker."""
        code = kap_code(ticker)
        data = self._get_json(f"member/filter/{quote(code)}")
        if not isinstance(data, list) or not data:
            raise SourceError(f"KAP has no company matching ticker {code!r}.")
        # The endpoint already filters by the code we passed; the first hit is the
        # best match (the payload carries no ticker field to disambiguate further).
        item = data[0]
        oid = item.get("mkkMemberOid")
        if not oid:
            raise SourceError(f"KAP response for {code!r} is missing 'mkkMemberOid'.")
        return KapMember(
            oid=str(oid),
            company_code=str(item.get("companyCode", "")),
            title=str(item.get("title", "")),
        )

    def download_financial_archive(
        self, oid: str, year: int, statement_type: str = "T"
    ) -> bytes:
        """Download the raw ZIP of financial-statement files for ``oid``/``year``."""
        raw = self._get_bytes(
            f"home-financial/download-file/{oid}/{year}/{statement_type}"
        )
        if raw[:2] != _ZIP_MAGIC:
            raise SourceError(
                f"KAP did not return a ZIP for member {oid} year {year} "
                f"(got {len(raw)} bytes). The company may not have filed statements "
                "for that period, or the endpoint changed."
            )
        return raw

    # -- HTTP edge -----------------------------------------------------------
    def _get(self, path: str) -> requests.Response:
        url = f"{self.BASE_URL}/{path}"
        try:
            resp = self._session.get(url, headers=self.HEADERS, timeout=self._timeout)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise SourceError(f"KAP request failed ({url}): {e}") from e
        return resp

    def _get_json(self, path: str) -> Any:
        resp = self._get(path)
        try:
            return resp.json()
        except ValueError as e:
            raise SourceError(f"KAP returned non-JSON for {path}: {e}") from e

    def _get_bytes(self, path: str) -> bytes:
        return self._get(path).content


class KapSource:
    """``StatementSource`` over KAP: ticker -> financial-statement files on disk."""

    def __init__(self, client: Optional[KapClient] = None) -> None:
        self._client = client or KapClient()

    def fetch(self, ticker: str, *, year: int, dest_dir: Path) -> list[Path]:
        member = self._client.resolve_member(ticker)
        archive = self._client.download_financial_archive(member.oid, year)
        dest_dir.mkdir(parents=True, exist_ok=True)
        return _extract_archive(archive, dest_dir, stem=f"{kap_code(ticker)}_{year}")


def _extract_archive(data: bytes, dest_dir: Path, *, stem: str) -> list[Path]:
    """Extract a KAP ZIP into ``dest_dir``, flattening names (zip-slip safe)."""
    written: list[Path] = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for name in zf.namelist():
                safe = Path(name).name  # drop any path components in the archive
                if not safe:  # directory entry
                    continue
                out = dest_dir / f"{stem}__{safe}"
                out.write_bytes(zf.read(name))
                written.append(out)
    except zipfile.BadZipFile as e:
        raise SourceError(f"KAP archive is not a readable ZIP: {e}") from e
    if not written:
        raise SourceError("KAP archive contained no extractable files.")
    return written
