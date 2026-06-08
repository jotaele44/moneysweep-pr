"""Smoke tests for download_fec after the BaseDownloader migration.

These pin the run()/_session/_fetch_cycle contract that run_all.py and the
shared lifecycle depend on. All network is mocked; no real HTTP.
"""

from __future__ import annotations

import pandas as pd
from unittest.mock import patch

import scripts.download_fec as fec


def _sample_record():
    return {
        "cycle": 2020,
        "contributor_name": "DOE, JANE",
        "contributor_city": "SAN JUAN",
        "contributor_zip_code": "00901",
        "contributor_employer": "ACME",
        "contributor_occupation": "ENGINEER",
        "contribution_receipt_amount": "250",
        "contribution_receipt_date": "2020-03-01",
        "committee_id": "C001",
        "committee_name": "FRIENDS OF X",
        "candidate_id": "H001",
        "candidate_name": "X, CANDIDATE",
        "report_year": "2020",
        "election_type": "P",
        "memo_text": "",
        "is_individual": True,
    }


def test_session_sets_api_key_header():
    s = fec._session("my-key")
    assert s.headers["X-Api-Key"] == "my-key"
    assert s.headers["User-Agent"].startswith("ContractSweeper/")
    s.close()


def test_run_writes_master_with_records(tmp_path):
    with patch.object(fec, "_fetch_cycle", return_value=[_sample_record()]):
        result = fec.run(root=tmp_path, api_key="k", force=True)

    assert result["status"] == "OK"
    assert result["rows"] == 1  # same record across all cycles dedupes to one
    master = tmp_path / "data" / "staging" / "processed" / "pr_fec_contributions.csv"
    assert master.exists()
    df = pd.read_csv(master, dtype=str)
    assert list(df.columns) == fec.OUTPUT_COLUMNS
    assert df.iloc[0]["contributor_name"] == "DOE, JANE"


def test_run_empty_when_no_records(tmp_path):
    with patch.object(fec, "_fetch_cycle", return_value=[]):
        result = fec.run(root=tmp_path, api_key="k", force=True)

    assert result["status"] == "EMPTY"
    assert result["rows"] == 0
    master = tmp_path / "data" / "staging" / "processed" / "pr_fec_contributions.csv"
    assert master.exists()


def test_fetch_cycle_paginates_via_get():
    """_fetch_cycle should walk pages until pagination.pages is reached."""
    pages = [
        {
            "results": [{"contributor_name": "A", "entity_type": "IND"}],
            "pagination": {"pages": 2, "count": 2},
        },
        {
            "results": [{"contributor_name": "B", "entity_type": "ORG"}],
            "pagination": {"pages": 2, "count": 2},
        },
    ]
    with patch.object(fec, "_get", side_effect=pages) as mock_get:
        recs = fec._fetch_cycle(session=None, cycle=2020, sleep_s=0, logger=_Logger())

    assert [r["contributor_name"] for r in recs] == ["A", "B"]
    assert recs[0]["is_individual"] is True
    assert recs[1]["is_individual"] is False
    assert mock_get.call_count == 2


def test_fetch_cycle_stops_on_none():
    with patch.object(fec, "_get", return_value=None):
        recs = fec._fetch_cycle(session=None, cycle=2020, sleep_s=0, logger=_Logger())
    assert recs == []


class _Logger:
    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass
