"""Shared lifecycle for the ``scripts/download_*.py`` family.

The ~70 downloaders each re-implemented the same building blocks: a configured
``requests.Session``, a GET-with-retry loop (HTTP 429 backoff, 4xx terminal, 5xx
/transport retry), a pagination loop, a "file has data" check, and a CSV write.
This module factors those out **once** so a downloader becomes its endpoint/filter
shape plus a record-flattening function.

Design notes
------------
* The retry loop is built on :func:`contract_sweeper.runtime.retry_runtime.with_retry`
  (+ :class:`RetryPolicy`) and pagination on
  :func:`contract_sweeper.runtime.pagination_runtime.paginate` (+ :class:`PageResult`),
  so this is genuine reuse, not a fourth copy.
* Both a **functional core** (:func:`build_session`, :func:`http_get_json`,
  :func:`file_has_data`, :func:`write_csv`) and a small OO wrapper
  (:class:`BaseDownloader`) are provided. The functional core lets existing
  downloaders keep their module-level ``_session`` / ``_get`` seams (which tests
  patch) while sharing one implementation; the class is for new downloaders.
* Behavior-preserving: returns parsed JSON on success, ``None`` on 4xx, retries
  on 429 and 5xx/transport errors up to ``max_retries`` then returns ``None``.
  Only the inter-attempt *sleep schedule* changes (jittered-exponential instead
  of a fixed list); sleeps are injected so they are mocked in tests.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

import pandas as pd
import requests

from scripts.config import PROJECT_ROOT, setup_logging
from contract_sweeper.runtime.pagination_runtime import PageResult, paginate
from contract_sweeper.runtime.retry_runtime import (
    RetryExhausted,
    RetryPolicy,
    with_retry,
)

__all__ = [
    "HttpConfig",
    "PageResult",
    "paginate",
    "build_session",
    "http_get_json",
    "http_post_json",
    "file_has_data",
    "write_csv",
    "BaseDownloader",
]

_DEFAULT_USER_AGENT = "ContractSweeper/1.0 (PR federal spending research)"


@dataclass(frozen=True)
class HttpConfig:
    """Per-source HTTP tuning. Defaults match the historical downloader values."""

    user_agent: str = _DEFAULT_USER_AGENT
    extra_headers: dict[str, str] = field(default_factory=dict)
    max_retries: int = 3
    base_delay_seconds: float = 5.0
    max_delay_seconds: float = 30.0
    page_sleep: float = 0.3
    rate_limit_sleep: float = 60.0
    timeout: int = 60


class _RateLimited(Exception):
    """Internal marker so a 429 is retried by :func:`with_retry`."""


def build_session(
    user_agent: str = _DEFAULT_USER_AGENT,
    extra_headers: dict[str, str] | None = None,
) -> requests.Session:
    """Return a ``requests.Session`` with the standard JSON headers."""
    s = requests.Session()
    headers = {"User-Agent": user_agent, "Accept": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    s.headers.update(headers)
    return s


def _http_json(
    do_request: Callable[[], requests.Response],
    *,
    logger,
    config: HttpConfig,
    sleeper: Callable[[float], None],
) -> dict | None:
    """Shared retry core for :func:`http_get_json` / :func:`http_post_json`.

    ``do_request`` performs one HTTP call and returns the ``Response``. The loop:
    429 -> long sleep then retry, 4xx -> terminal ``None``, 5xx / transport error
    -> retry, success -> short inter-page sleep then parsed JSON.
    """

    def _once() -> dict | None:
        resp = do_request()
        if resp.status_code == 429:
            logger.warning("  Rate limited — sleeping %ss", config.rate_limit_sleep)
            sleeper(config.rate_limit_sleep)
            raise _RateLimited()
        if 400 <= resp.status_code < 500:
            logger.error("  HTTP %s: %s", resp.status_code, resp.text[:200])
            return None
        resp.raise_for_status()
        sleeper(config.page_sleep)
        return resp.json()

    policy = RetryPolicy(
        max_attempts=config.max_retries,
        base_delay_seconds=config.base_delay_seconds,
        max_delay_seconds=config.max_delay_seconds,
    )
    try:
        return with_retry(
            _once,
            policy=policy,
            retry_on=(requests.RequestException, _RateLimited),
            sleeper=sleeper,
        )
    except RetryExhausted:
        logger.error("  All %d attempts failed", config.max_retries)
        return None


def http_get_json(
    session: requests.Session,
    url: str,
    params: dict,
    *,
    logger,
    config: HttpConfig | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict | None:
    """GET ``url`` with retry; return parsed JSON, or ``None`` on 4xx / exhaustion.

    Mirrors the proven downloader loop: 429 -> long sleep then retry, 4xx ->
    terminal ``None``, 5xx / transport error -> retry, success -> short
    inter-page sleep then JSON. Built on :func:`with_retry`.
    """
    config = config or HttpConfig()
    return _http_json(
        lambda: session.get(url, params=params, timeout=config.timeout),
        logger=logger,
        config=config,
        sleeper=sleeper,
    )


def http_post_json(
    session: requests.Session,
    url: str,
    payload: dict,
    *,
    logger,
    config: HttpConfig | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict | None:
    """POST ``payload`` as JSON with retry; return parsed JSON, or ``None``.

    The POST analogue of :func:`http_get_json` (the USASpending family and other
    POST-query APIs). Same retry semantics; built on the shared :func:`_http_json`
    core so there is a single retry implementation.
    """
    config = config or HttpConfig()
    return _http_json(
        lambda: session.post(url, json=payload, timeout=config.timeout),
        logger=logger,
        config=config,
        sleeper=sleeper,
    )


def file_has_data(path: Path | str) -> bool:
    """True if ``path`` is a CSV that exists and has at least one data row."""
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return False
    try:
        with p.open("r", encoding="utf-8") as fh:
            header = fh.readline()
            if not header.strip():
                return False
            return bool(fh.readline().strip())
    except OSError:
        return False


def write_csv(df: pd.DataFrame, path: Path | str) -> Path:
    """Write ``df`` to ``path`` with the downloader-standard options."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(p, index=False, encoding="utf-8")
    return p


class BaseDownloader:
    """Lifecycle wrapper for a single source. Subclass for new downloaders.

    Holds the session, logger, HTTP config and standard output paths so a
    concrete downloader only supplies endpoint/filter shape and record mapping.
    """

    source: str = ""

    def __init__(
        self,
        source: str | None = None,
        root: Path | str | None = None,
        *,
        http: HttpConfig | None = None,
        logger=None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.source = source or self.source
        if not self.source:
            raise ValueError("BaseDownloader requires a non-empty source name")
        self.root = Path(root) if root is not None else PROJECT_ROOT
        self.http = http or HttpConfig()
        self.logger = logger or setup_logging(f"download_{self.source}")
        self._sleeper = sleeper
        self._session: requests.Session | None = None

    # -- paths --------------------------------------------------------------
    @property
    def raw_dir(self) -> Path:
        p = self.root / "data" / "staging" / "raw" / self.source
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def processed_dir(self) -> Path:
        p = self.root / "data" / "staging" / "processed"
        p.mkdir(parents=True, exist_ok=True)
        return p

    # -- http ---------------------------------------------------------------
    def session(self) -> requests.Session:
        if self._session is None:
            self._session = build_session(self.http.user_agent, self.http.extra_headers)
        return self._session

    def get(self, url: str, params: dict) -> dict | None:
        return http_get_json(
            self.session(),
            url,
            params,
            logger=self.logger,
            config=self.http,
            sleeper=self._sleeper,
        )

    def post(self, url: str, payload: dict) -> dict | None:
        return http_post_json(
            self.session(),
            url,
            payload,
            logger=self.logger,
            config=self.http,
            sleeper=self._sleeper,
        )

    def paginate(
        self,
        fetch: Callable[[Any], PageResult],
        *,
        start_marker: Any = None,
        max_pages: int | None = None,
    ) -> Iterator[Any]:
        """Yield records across pages; ``fetch(marker)`` returns a PageResult."""
        return paginate(fetch, start_marker=start_marker, max_pages=max_pages)

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None

    # -- io -----------------------------------------------------------------
    @staticmethod
    def file_has_data(path: Path | str) -> bool:
        return file_has_data(path)

    def write_csv(self, df: pd.DataFrame, path: Path | str) -> Path:
        return write_csv(df, path)
