"""Pagination helper for ingestion scripts.

Supports three styles common to USAspending / OpenFEMA / FEC / LDA:
  - page number (page=1,2,3...)
  - offset/limit
  - cursor / next_page_token

Stdlib only. The fetcher callable is provided by the ingestion script and
must return a tuple of (records, next_marker). next_marker is None to stop.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterator


@dataclass(frozen=True)
class PageResult:
    records: list[Any]
    next_marker: Any | None  # page #, offset, cursor, or None to terminate


def paginate(
    fetch: Callable[[Any], PageResult],
    *,
    start_marker: Any = None,
    max_pages: int | None = None,
) -> Iterator[Any]:
    """Iterate over records across pages until fetch returns next_marker=None.

    Yields raw records, not PageResult, so callers don't have to flatten.
    `max_pages` defends against runaway pagination loops.
    """
    marker = start_marker
    pages = 0
    while True:
        if max_pages is not None and pages >= max_pages:
            return
        result = fetch(marker)
        for r in result.records:
            yield r
        pages += 1
        if result.next_marker is None:
            return
        marker = result.next_marker
