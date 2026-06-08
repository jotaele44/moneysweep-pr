"""Smoke tests for download_doj_grants after the BaseDownloader migration.

Pins the run()/_session/_fetch_page/_paginate contract for the USASpending
POST family (doj_grants is the canonical shape shared by ed/epa/oia/usace_civil/
hhs/haf). All network is mocked; no real HTTP.
"""

from __future__ import annotations

import pandas as pd
from unittest.mock import patch

import scripts.download_doj_grants as doj


def _sample_result():
    return {
        "Award ID": "DOJ-1",
        "Recipient Name": "PR POLICE DEPT",
        "recipient_uei": "ABC123",
        "Awarding Agency": "Department of Justice",
        "Awarding Sub Agency": "OJP",
        "Award Amount": "100000",
        "Start Date": "2019-05-01",
        "Award Type": "02",
        "Place of Performance State Code": "PR",
        "Place of Performance County Name": "SAN JUAN",
        "Description": "BYRNE JAG",
    }


def test_session_uses_shared_builder():
    s = doj._session()
    assert s.headers["User-Agent"] == "ContractSweeper/1.0"
    assert s.headers["Accept"] == "application/json"
    s.close()


def test_paginate_walks_pages_via_post():
    """_paginate should follow page_metadata.has_next_page across POST pages."""
    pages = [
        {"results": [{"Award ID": "A"}], "page_metadata": {"has_next_page": True}},
        {"results": [{"Award ID": "B"}], "page_metadata": {"has_next_page": False}},
    ]
    with patch.object(doj, "_fetch_page", side_effect=pages) as mock_fetch:
        recs = doj._paginate(session=None, base_payload={"filters": {}}, logger=_Logger())

    assert [r["Award ID"] for r in recs] == ["A", "B"]
    assert mock_fetch.call_count == 2


def test_paginate_stops_on_none():
    with patch.object(doj, "_fetch_page", return_value=None):
        recs = doj._paginate(session=None, base_payload={}, logger=_Logger())
    assert recs == []


def test_paginate_stops_on_empty_results():
    with patch.object(doj, "_fetch_page", return_value={"results": []}):
        recs = doj._paginate(session=None, base_payload={}, logger=_Logger())
    assert recs == []


def test_run_writes_master_with_records(tmp_path):
    with patch.object(doj, "_paginate", return_value=[_sample_result()]):
        summary = doj.run(root=tmp_path)

    # 8 fetches (4 windows x pop/recipient) of the same award dedupe to one row.
    assert summary["master_rows"] == 1
    master = tmp_path / "data" / "staging" / "processed" / "pr_doj_grants_master.csv"
    assert master.exists()
    df = pd.read_csv(master, dtype=str)
    assert df.iloc[0]["award_id"] == "DOJ-1"
    assert df.iloc[0]["recipient_name"] == "PR POLICE DEPT"
    assert df.iloc[0]["source_dataset"] == "doj_grants"


class _Logger:
    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass
