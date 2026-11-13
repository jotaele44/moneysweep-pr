from __future__ import annotations

import json
import sqlite3

import pytest

from moneysweep.runtime.source_database import materialize_source


def test_materialize_source_is_idempotent_and_preserves_provenance(tmp_path):
    output = tmp_path / "data" / "staging" / "sample.csv"
    output.parent.mkdir(parents=True)
    output.write_text("award_id,amount\nA-1,12.50\nA-2,7\n", encoding="utf-8")
    source = {
        "source_id": "sample_financial_source",
        "required": True,
        "family": "federal",
        "expected_outputs": ["data/staging/sample.csv"],
    }

    first = materialize_source(tmp_path, source)
    second = materialize_source(tmp_path, source)

    assert first["status"] == second["status"] == "IMPORTED"
    assert first["rows"] == second["rows"] == 2
    connection = sqlite3.connect(tmp_path / "data/moneysweep_sources.sqlite3")
    try:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM financial_records WHERE source_id=?",
                ("sample_financial_source",),
            ).fetchone()[0]
            == 2
        )
        payload = json.loads(
            connection.execute("SELECT payload_json FROM financial_records").fetchone()[0]
        )
        assert payload["award_id"] == "A-1"
        assert connection.execute("SELECT COUNT(*) FROM source_runs").fetchone()[0] == 2
    finally:
        connection.close()


@pytest.mark.parametrize("expected_output", ["../outside.csv", "data/staging/linked.csv"])
def test_materialize_source_rejects_outputs_outside_workspace(tmp_path, expected_output):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.csv"
    outside.write_text("record_id\nsensitive\n", encoding="utf-8")
    if expected_output == "data/staging/linked.csv":
        linked = workspace / expected_output
        linked.parent.mkdir(parents=True)
        linked.symlink_to(outside)

    result = materialize_source(
        workspace,
        {
            "source_id": "outside_source",
            "required": False,
            "family": "test",
            "expected_outputs": [expected_output],
        },
    )

    assert result["status"] == "NO_DATA"
    assert result["files"] == result["rows"] == 0
