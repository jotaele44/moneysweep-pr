"""Unit tests for the shared downloader lifecycle (runtime.base_downloader)."""
from __future__ import annotations

import pandas as pd
import pytest
import requests

from contract_sweeper.runtime.base_downloader import (
    BaseDownloader,
    HttpConfig,
    PageResult,
    build_session,
    file_has_data,
    http_get_json,
    write_csv,
)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

class _Resp:
    def __init__(self, status=200, json_data=None, exc=None):
        self.status_code = status
        self._json = json_data if json_data is not None else {}
        self._exc = exc
        self.text = "error body"

    def raise_for_status(self):
        if self.status_code >= 500:
            raise requests.RequestException(f"HTTP {self.status_code}")

    def json(self):
        return self._json


class _FakeSession:
    """Returns queued responses; a queued Exception is raised as a transport error."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _noop_sleep(_):
    pass


# ---------------------------------------------------------------------------
# build_session
# ---------------------------------------------------------------------------

def test_build_session_sets_default_headers():
    s = build_session()
    assert s.headers["User-Agent"].startswith("ContractSweeper/")
    assert s.headers["Accept"] == "application/json"
    s.close()


def test_build_session_merges_extra_headers():
    s = build_session("UA/9", {"X-Api-Key": "secret", "Authorization": "Token t"})
    assert s.headers["User-Agent"] == "UA/9"
    assert s.headers["X-Api-Key"] == "secret"
    assert s.headers["Authorization"] == "Token t"
    s.close()


# ---------------------------------------------------------------------------
# http_get_json
# ---------------------------------------------------------------------------

def test_http_get_json_success_returns_payload():
    session = _FakeSession([_Resp(200, {"results": [1, 2]})])
    out = http_get_json(session, "http://x", {}, logger=_Logger(), sleeper=_noop_sleep)
    assert out == {"results": [1, 2]}


def test_http_get_json_4xx_is_terminal_none_no_retry():
    session = _FakeSession([_Resp(404)])
    out = http_get_json(session, "http://x", {}, logger=_Logger(), sleeper=_noop_sleep)
    assert out is None
    assert len(session.calls) == 1  # did NOT retry a 4xx


def test_http_get_json_retries_5xx_then_succeeds():
    session = _FakeSession([_Resp(503), _Resp(200, {"ok": True})])
    cfg = HttpConfig(max_retries=3)
    out = http_get_json(session, "http://x", {}, logger=_Logger(), config=cfg, sleeper=_noop_sleep)
    assert out == {"ok": True}
    assert len(session.calls) == 2


def test_http_get_json_retries_transport_error_then_exhausts():
    session = _FakeSession([requests.RequestException("boom")] * 3)
    cfg = HttpConfig(max_retries=3)
    out = http_get_json(session, "http://x", {}, logger=_Logger(), config=cfg, sleeper=_noop_sleep)
    assert out is None
    assert len(session.calls) == 3


def test_http_get_json_429_is_retried():
    session = _FakeSession([_Resp(429), _Resp(200, {"ok": 1})])
    cfg = HttpConfig(max_retries=3)
    sleeps = []
    out = http_get_json(session, "http://x", {}, logger=_Logger(), config=cfg, sleeper=sleeps.append)
    assert out == {"ok": 1}
    assert len(session.calls) == 2
    # the 429 path triggered the long rate-limit sleep
    assert cfg.rate_limit_sleep in sleeps


# ---------------------------------------------------------------------------
# file_has_data / write_csv
# ---------------------------------------------------------------------------

def test_file_has_data(tmp_path):
    missing = tmp_path / "nope.csv"
    assert file_has_data(missing) is False

    header_only = tmp_path / "header.csv"
    header_only.write_text("a,b\n")
    assert file_has_data(header_only) is False

    with_rows = tmp_path / "data.csv"
    with_rows.write_text("a,b\n1,2\n")
    assert file_has_data(with_rows) is True


def test_write_csv_roundtrip(tmp_path):
    df = pd.DataFrame([{"x": 1, "y": "z"}])
    out = write_csv(df, tmp_path / "sub" / "out.csv")
    assert out.exists()
    back = pd.read_csv(out)
    assert list(back.columns) == ["x", "y"]
    assert len(back) == 1


# ---------------------------------------------------------------------------
# BaseDownloader class
# ---------------------------------------------------------------------------

def test_base_downloader_paths(tmp_path):
    dl = BaseDownloader("demo", root=tmp_path, logger=_Logger(), sleeper=_noop_sleep)
    assert dl.raw_dir == tmp_path / "data" / "staging" / "raw" / "demo"
    assert dl.raw_dir.exists()
    assert dl.processed_dir == tmp_path / "data" / "staging" / "processed"
    assert dl.processed_dir.exists()


def test_base_downloader_requires_source():
    with pytest.raises(ValueError):
        BaseDownloader(logger=_Logger())


def test_base_downloader_get_uses_injected_session(tmp_path, monkeypatch):
    dl = BaseDownloader("demo", root=tmp_path, logger=_Logger(), sleeper=_noop_sleep)
    dl._session = _FakeSession([_Resp(200, {"v": 5})])
    assert dl.get("http://x", {}) == {"v": 5}


def test_base_downloader_paginate_walks_markers(tmp_path):
    dl = BaseDownloader("demo", root=tmp_path, logger=_Logger(), sleeper=_noop_sleep)
    pages = {
        0: PageResult([1, 2], 1),
        1: PageResult([3], 2),
        2: PageResult([4], None),
    }
    out = list(dl.paginate(lambda m: pages[m], start_marker=0))
    assert out == [1, 2, 3, 4]


class _Logger:
    """Minimal logger that swallows the printf-style calls base_downloader makes."""

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass
