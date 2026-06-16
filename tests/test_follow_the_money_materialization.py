"""End-to-end proof that follow_the_money materializes its legit outputs offline.

Exercises the offline path: with the committed legit dropzone inputs
(Municipal_Blind_Score_CORE6.csv, municipality_political_federal_bridge.csv,
facility_matches_cross_exam.csv) the producer materializes
pr_ftm_municipal_bridge.csv and pr_ftm_facility_matches.csv with no network. These
inputs are git-tracked, so this test is reproducible in CI.

Also guards the Epstein separation: the EP_PR_PRBank_* records must NOT live in the
dropzone and the producer must not reference them.
"""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

import pytest

from scripts.ingest_follow_the_money import (
    FACILITY_COLUMNS,
    MUNI_BRIDGE_COLUMNS,
    run,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parent.parent
DROPZONE = REPO_ROOT / "data" / "raw" / "follow_the_money"
LEGIT_INPUTS = (
    "Municipal_Blind_Score_CORE6.csv",
    "municipality_political_federal_bridge.csv",
    "facility_matches_cross_exam.csv",
)


def _seed_offline_root(tmp_path: Path) -> Path:
    dst = tmp_path / "data" / "raw" / "follow_the_money"
    dst.mkdir(parents=True, exist_ok=True)
    for name in LEGIT_INPUTS:
        shutil.copy(DROPZONE / name, dst / name)
    return tmp_path


def test_legit_inputs_present_and_tracked():
    for name in LEGIT_INPUTS:
        assert (DROPZONE / name).exists(), f"missing committed input: {name}"


def test_offline_run_materializes_municipal_and_facility_outputs(tmp_path):
    root = _seed_offline_root(tmp_path)
    result = run(root=root)

    assert result["status"] == "OK"
    assert result["rows"] > 0

    out_dir = root / "data" / "staging" / "processed"
    muni = out_dir / "pr_ftm_municipal_bridge.csv"
    fac = out_dir / "pr_ftm_facility_matches.csv"

    muni_rows = list(csv.DictReader(muni.open(encoding="utf-8")))
    fac_rows = list(csv.DictReader(fac.open(encoding="utf-8")))

    assert muni_rows, "municipal bridge should be non-empty from committed inputs"
    assert fac_rows, "facility matches should be non-empty from committed inputs"
    assert list(muni_rows[0].keys()) == MUNI_BRIDGE_COLUMNS
    assert list(fac_rows[0].keys()) == FACILITY_COLUMNS

    # The Epstein wire-ledger output is never produced.
    assert not (out_dir / "pr_ftm_wire_ledger.csv").exists()


def test_epstein_records_separated_from_dropzone():
    """Separation guard: no EP_PR_PRBank_* file under the public-money dropzone."""
    stray = list(DROPZONE.glob("EP_PR_PRBank_*"))
    assert stray == [], f"Epstein wire records must not live in the dropzone: {stray}"


def test_producer_does_not_reference_epstein_inputs():
    src = (REPO_ROOT / "scripts" / "ingest_follow_the_money.py").read_text(encoding="utf-8")
    # The producer may *explain* the separation in its docstring, but must not
    # read the Epstein wire files or write the wire-ledger output.
    assert '_read("EP_PR_PRBank' not in src
    assert "pr_ftm_wire_ledger" not in src
