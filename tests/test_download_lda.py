"""Smoke tests for download_lda after the BaseDownloader migration.

Pins the run()/_session/_fetch_pass contract and the cursor-pagination path.
All network is mocked; no real HTTP.
"""

from __future__ import annotations

import pandas as pd
from unittest.mock import patch

import scripts.download_lda as lda


def test_session_authorization_header_optional():
    with_key = lda._session("tok")
    assert with_key.headers["Authorization"] == "Token tok"
    with_key.close()

    no_key = lda._session(None)
    assert "Authorization" not in no_key.headers
    no_key.close()


def test_run_falls_back_to_seed_rows(tmp_path):
    """With no API rows, run() still emits the KNOWN_LDA_DATA seed and is OK."""
    with patch.object(lda, "_fetch_pass", return_value=[]):
        result = lda.run(root=tmp_path, api_key=None, force=True)

    assert result["status"] == "OK"
    assert result["rows"] == len(lda.KNOWN_LDA_DATA)
    out = tmp_path / "data" / "staging" / "processed" / "pr_lda_filings.csv"
    assert out.exists()
    df = pd.read_csv(out, dtype=str)
    # OUTPUT_COLUMNS are all present (run() also writes two numeric helper cols)
    assert set(lda.OUTPUT_COLUMNS).issubset(df.columns)


def test_run_dedupes_by_filing_uuid(tmp_path):
    dup = dict(lda.KNOWN_LDA_DATA[0])
    with patch.object(lda, "_fetch_pass", return_value=[dup]):
        result = lda.run(root=tmp_path, api_key=None, force=True)
    # the duplicate of seed-001 collapses; total stays at the seed count
    assert result["rows"] == len(lda.KNOWN_LDA_DATA)


def test_fetch_pass_walks_next_cursor():
    pages = [
        {
            "results": [{"filing_uuid": "u1", "client": {"state": "PR"}}],
            "count": 2,
            "next": "http://next",
        },
        {"results": [{"filing_uuid": "u2", "client": {"state": "PR"}}], "count": 2, "next": None},
    ]
    with patch.object(lda, "_get", side_effect=pages) as mock_get:
        recs = lda._fetch_pass(session=None, state_param="client_state", logger=_Logger())

    assert [r["filing_uuid"] for r in recs] == ["u1", "u2"]
    assert mock_get.call_count == 2


def test_fetch_pass_stops_on_none():
    with patch.object(lda, "_get", return_value=None):
        recs = lda._fetch_pass(session=None, state_param="client_state", logger=_Logger())
    assert recs == []


class _Logger:
    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass
