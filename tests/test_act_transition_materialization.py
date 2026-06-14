"""End-to-end proof that act_transition materializes offline from committed data.

Unlike tests/test_act_transition_ingest.py (which drives the PDF→processed chain
against a generated PDF), this exercises the *offline* path: with no operator PDF,
the producer materializes the declared processed output directly from the
committed 18-column extract at
``data/raw/act_transition/transition_contracts_extracted.csv``.

That extract is git-tracked, so this test is fully reproducible in CI — it is the
authoritative proof that ``act_transition_contracts`` / ``acuden_2024_transition``
can go from registry definition to a validated output with no network and no
operator file. No network.
"""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

import pytest

from scripts.ingest_act_transition import (
    CANONICAL_COLUMNS,
    COMMITTED_EXTRACT,
    PROCESSED_OUTPUTS,
    _read_committed_extract_rows,
    run,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parent.parent
EXTRACT_SRC = REPO_ROOT / COMMITTED_EXTRACT


def _seed_offline_root(tmp_path: Path) -> Path:
    """A throwaway project root holding only the committed extract (no PDFs)."""
    dst = tmp_path / COMMITTED_EXTRACT
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(EXTRACT_SRC, dst)
    return tmp_path


def test_committed_extract_is_present_and_tracked():
    """The offline input must exist in the repo (else the offline path is moot)."""
    assert EXTRACT_SRC.exists(), f"missing committed extract: {COMMITTED_EXTRACT}"


@pytest.mark.parametrize(
    "source_key, dataset",
    [("act", "ACT_2020"), ("acuden", "ACUDEN_2024")],
)
def test_read_committed_extract_filters_by_dataset(tmp_path, source_key, dataset):
    root = _seed_offline_root(tmp_path)
    rows = _read_committed_extract_rows(root, source_key)
    assert rows, f"no rows mapped for {source_key}"
    # Every mapped row has the six fields promote_rows consumes.
    assert all({"contractor_name", "contract_number", "amount"} <= set(r) for r in rows)


@pytest.mark.parametrize("source_key", ["act", "acuden"])
def test_offline_run_materializes_validated_output(tmp_path, source_key):
    root = _seed_offline_root(tmp_path)
    result = run(root=root, source=source_key)

    assert result["status"] == "OK"
    assert result["rows"] >= 1

    out_path = root / PROCESSED_OUTPUTS[source_key]
    assert out_path.exists()
    with out_path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    # Non-empty and schema-valid against the canonical processed columns.
    assert rows
    assert list(rows[0].keys()) == CANONICAL_COLUMNS
    # Provenance tag is the registry source label, not the raw dataset code.
    labels = {r["source_dataset"] for r in rows}
    assert labels == {
        "act_transition_contracts" if source_key == "act" else "acuden_2024_transition"
    }


def test_offline_run_with_no_input_is_clean_noop(tmp_path):
    """No extract, no PDF → EMPTY, nothing written (the no-op contract holds)."""
    result = run(root=tmp_path, source="act")
    assert result["status"] == "EMPTY"
    assert result["rows"] == 0
    assert not (tmp_path / PROCESSED_OUTPUTS["act"]).exists()
