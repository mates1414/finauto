"""KAP statement source: OID resolution, archive download, and extraction.

No live network — a fake ``requests.Session`` is injected into ``KapClient`` and
returns recorded payload shapes (the real ``member/filter`` JSON and an in-memory
ZIP that mirrors KAP's .xls bundle).
"""

from __future__ import annotations

import io
import zipfile

import pytest
import requests

from finauto.ingestion.sources.base import SourceError, get_source
from finauto.ingestion.sources.kap import (
    KapClient,
    KapSource,
    kap_code,
    select_statement_pdfs,
)


class FakeResponse:
    def __init__(self, *, json_data=None, content=b"", status=200):
        self._json = json_data
        self.content = content
        self.status_code = status

    def json(self):
        if self._json is None:
            raise ValueError("response is not JSON")
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")


class FakeSession:
    """Routes a GET to the first response whose key is a substring of the URL."""

    def __init__(self, routes: dict[str, FakeResponse]):
        self.routes = routes
        self.calls: list[str] = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        for key, resp in self.routes.items():
            if key in url:
                return resp
        raise AssertionError(f"unexpected URL: {url}")


# Real shape returned by GET /tr/api/member/filter/THYAO
THYAO_MEMBER = [
    {
        "companyCode": "1107",
        "mkkMemberOid": "4028e4a140f2ed720140f376bebb01a7",
        "title": "TÜRK HAVA YOLLARI A.O.",
        "permaLink": "1107-turk-hava-yollari-a-o",
    }
]


def _make_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("BILANCO.xls", b"<table>balance</table>")
        zf.writestr("subdir/GELIR_TABLOSU.xls", b"<table>income</table>")
    return buf.getvalue()


def test_kap_code_strips_suffix():
    assert kap_code("THYAO.IS") == "THYAO"
    assert kap_code("bimas") == "BIMAS"


def test_fetch_writes_flattened_files(tmp_path):
    session = FakeSession(
        {
            "member/filter/THYAO": FakeResponse(json_data=THYAO_MEMBER),
            "home-financial/download-file/4028e4a140f2ed720140f376bebb01a7/2024/T": (
                FakeResponse(content=_make_zip())
            ),
        }
    )
    src = KapSource(client=KapClient(session=session))

    paths = src.fetch("THYAO.IS", year=2024, dest_dir=tmp_path)

    names = sorted(p.name for p in paths)
    # zip nested path flattened; stem = <code>_<year>
    assert names == ["THYAO_2024__BILANCO.xls", "THYAO_2024__GELIR_TABLOSU.xls"]
    assert all(p.exists() and p.read_bytes() for p in paths)
    # ".IS" was stripped before hitting KAP's filter endpoint
    assert any("member/filter/THYAO" in c for c in session.calls)


def test_resolve_member_empty_raises():
    session = FakeSession({"member/filter/NOPE": FakeResponse(json_data=[])})
    with pytest.raises(SourceError, match="no company"):
        KapClient(session=session).resolve_member("NOPE.IS")


def test_resolve_member_missing_oid_raises():
    session = FakeSession(
        {"member/filter/X": FakeResponse(json_data=[{"companyCode": "1"}])}
    )
    with pytest.raises(SourceError, match="mkkMemberOid"):
        KapClient(session=session).resolve_member("X.IS")


def test_download_rejects_non_zip():
    session = FakeSession(
        {"home-financial/download-file/OID/2024/T": FakeResponse(content=b"<html>!")}
    )
    with pytest.raises(SourceError, match="ZIP"):
        KapClient(session=session).download_financial_archive("OID", 2024)


def test_request_failure_is_wrapped():
    class BoomSession:
        def get(self, *a, **k):
            raise requests.ConnectionError("network down")

    with pytest.raises(SourceError, match="request failed"):
        KapClient(session=BoomSession()).resolve_member("X.IS")


def test_get_source_factory():
    assert isinstance(get_source("kap"), KapSource)
    with pytest.raises(ValueError):
        get_source("bogus")


def _touch(p, size=1):
    p.write_bytes(b"x" * size)
    return p


def test_select_prefers_turkish_annual(tmp_path):
    # Mirrors a real THYAO 2024 bundle: TR + EN PDFs per quarter, plus an .xls.
    en = _touch(tmp_path / "(0)THY A.O. İng Aralık 2024.pdf", 50)
    tr_dec = _touch(tmp_path / "(1)THY A.O. Aralık 2024.pdf", 80)  # annual
    tr_mar = _touch(tmp_path / "(4)THY A.O. Mart 2024.pdf", 90)
    xls = _touch(tmp_path / "THYAO_1396940_2024_4.xls", 100)

    sel = select_statement_pdfs([en, tr_dec, tr_mar, xls])

    # December (annual) wins on period rank over March, despite March's larger size;
    # the English edition and the .xls are excluded.
    assert sel == [tr_dec]


def test_select_excludes_english_dotted_i(tmp_path):
    # The dotted-İ must be recognised as the English marker (Turkish casing trap).
    en = _touch(tmp_path / "THY A.O. İng. Aralık 2024.pdf")
    tr = _touch(tmp_path / "THY A.O. Aralık 2024.pdf")
    assert select_statement_pdfs([en, tr], latest_only=False) == [tr]


def test_select_size_tiebreak_when_period_unknown(tmp_path):
    small = _touch(tmp_path / "rapor_a.pdf", 10)
    big = _touch(tmp_path / "rapor_b.pdf", 200)
    assert select_statement_pdfs([small, big]) == [big]


def test_select_falls_back_when_only_english(tmp_path):
    en = _touch(tmp_path / "THY İng Aralık 2024.pdf")
    # language filter never empties the result on its own
    assert select_statement_pdfs([en]) == [en]


def test_select_ignores_non_pdf(tmp_path):
    xls = _touch(tmp_path / "THYAO_2024_4.xls")
    assert select_statement_pdfs([xls]) == []
