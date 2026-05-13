import csv
import json
from pathlib import Path

from contract_sweeper.validation.master_rebuild_validated import run_r4_9_master_rebuild


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_r4_9_fails_closed_without_manifest_backed_inputs(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scripts/build_unified_master.py").write_text(
        "NEW_MASTERS=[]\nEXPANSION_FILES=[]\n",
        encoding="utf-8",
    )

    _write_json(tmp_path / "data/exports/rebuild_status.json", {"phase_7_8_blocked": True})
    status = run_r4_9_master_rebuild(tmp_path)

    assert status["r4_9_gate_passed"] is False
    assert status["r4_9_blocker_count"] >= 1
    assert status["phase_7_8_blocked"] is True

    blockers = tmp_path / "data/review_queue/r4_9_rebuild_blockers.csv"
    assert blockers.exists()
    with blockers.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows
    assert rows[0]["exists"] == "False"
