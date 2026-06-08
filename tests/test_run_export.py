"""End-to-end test for the one-command federation export (scripts/run_export.py).

Proves the masters -> streams -> package -> validate chain produces a
production-valid v1.2.0 package from the committed sample master fixtures,
independent of the (paused) production pipeline. This is what the scheduled
`federation-export` workflow runs once real masters are available.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts import run_export, validate_export

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_MASTERS = REPO_ROOT / "tests" / "fixtures" / "sample_master_inputs"


def test_run_export_produces_valid_production_package(tmp_path):
    out_dir = tmp_path / "package"
    rc = run_export.run(processed_dir=SAMPLE_MASTERS, output_dir=out_dir, mode="production")
    assert rc == 0

    # Fail-closed validator agrees the package is production-valid.
    assert validate_export.validate_package(out_dir, mode="production") == []

    # All five streams + manifest landed, at the current contract version.
    for name in (
        "entities.jsonl",
        "sources.jsonl",
        "funding_awards.jsonl",
        "transactions.jsonl",
        "relationships.jsonl",
        "manifest.json",
    ):
        assert (out_dir / name).is_file()
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["export_contract_version"] == "1.2.0"
    assert manifest["mode"] == "production"
