"""Tests for the PRASA CER/CIP/completed-projects ingester (scripts.ingest_prasa_cer).

Hermetic, offline: operator CSV drops are simulated in a tmp dropzone; the no-files
no-op contract is also covered. No network.
"""

from __future__ import annotations

import csv

import pytest

from scripts.ingest_prasa_cer import CANONICAL_COLUMNS, SOURCES, normalize, run

pytestmark = pytest.mark.unit


def _write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def test_normalize_maps_aliases_and_drops_blank_rows():
    rows = normalize(
        [
            {
                "Proyecto": "Carraizo WTP Upgrade",
                "Costo": "$5,104,135.75",
                "Estatus": "Completed",
                "FY": "2023",
            },
            {"cuenta": "", "monto": ""},  # dropped (no item, no amount)
        ],
        "prasa_cip",
    )
    assert len(rows) == 1
    assert list(rows[0].keys()) == CANONICAL_COLUMNS
    assert rows[0]["item"] == "Carraizo WTP Upgrade"
    assert rows[0]["amount_usd"] == "5104135.75"
    assert rows[0]["category"] == "Completed"
    assert rows[0]["source_system"] == "prasa_cip"


@pytest.mark.parametrize("source_id", list(SOURCES))
def test_run_materializes_from_dropzone(tmp_path, source_id):
    sub = SOURCES[source_id]["subdir"]
    drop = tmp_path / "data" / "raw" / "PRASA" / sub / "export.csv"
    _write(
        drop,
        [
            {
                "project": "Vieques cleanup",
                "amount": "403852937.75",
                "status": "done",
                "year": "2022",
            }
        ],
    )

    result = run(root=tmp_path, source=source_id)
    assert result["status"] == "OK"
    assert result["rows"] == 1

    out = tmp_path / SOURCES[source_id]["output"]
    with out.open(encoding="utf-8", newline="") as f:
        out_rows = list(csv.DictReader(f))
    assert out_rows and list(out_rows[0].keys()) == CANONICAL_COLUMNS
    assert all(r["source_system"] == source_id for r in out_rows)


def test_run_no_dropzone_is_clean_empty(tmp_path):
    result = run(root=tmp_path, source="prasa_cer")
    assert result["status"] == "EMPTY"
    assert result["rows"] == 0
    # No-op contract: an empty-schema CSV is still written so downstream/audit can read it.
    out = tmp_path / SOURCES["prasa_cer"]["output"]
    assert out.exists()
    with out.open(encoding="utf-8", newline="") as f:
        assert next(csv.reader(f)) == CANONICAL_COLUMNS
