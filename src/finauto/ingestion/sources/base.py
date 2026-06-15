"""Pluggable raw-data sources: fetch financial-statement files for a ticker.

A *source* is the acquisition edge of the pipeline — it puts files on disk given
a ticker. Downstream stages consume those files unchanged (the LLM ``Extractor``
over PDFs, or, later, a structured-table parser over KAP's XLS bundle). Keeping
*fetch* separate from *extract* mirrors the ``ingestion/base.Extractor`` split:
add a source by implementing the protocol, never by branching in callers.

This is finauto's Phase-2 "KAP auto-download" entry point; the SaaS exposes it as
an endpoint that feeds the same extraction job as a manual upload.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class SourceError(Exception):
    """A data source could not return usable files (network, not-found, bad payload)."""


class StatementSource(Protocol):
    def fetch(self, ticker: str, *, year: int, dest_dir: Path) -> list[Path]:
        """Download financial-statement file(s) for ``ticker`` into ``dest_dir``.

        Returns the written file paths. Raises :class:`SourceError` on any failure
        (no match, missing period, malformed payload) so callers can degrade
        cleanly instead of guessing.
        """
        ...


def get_source(name: str = "kap") -> StatementSource:
    """Factory mirroring ``ingestion.base.get_extractor``. Add a source here, once."""
    if name == "kap":
        from .kap import KapSource

        return KapSource()
    raise ValueError(f"unknown statement source: {name!r}")
