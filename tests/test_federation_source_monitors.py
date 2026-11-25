"""Tests for the source_monitors stream (thehub-pr ADR 0013) in scripts/federation_export.py.

The stream must equal, field for field, what thehub-pr's ADR 0012 registry reader
(``_parse_moneysweep``) derived from ``reports/source_registry_status.csv``, so the Hub
can switch moneysweep-pr from the reader to the stream without changing any row."""

import csv
import hashlib
import json
import re
from pathlib import Path

import prii_export_utils
import pytest
from prii_export_utils import record_run

from scripts import federation_export as fx

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY = "reports/source_registry_status.csv"
STATE = "data/source_run_state.json"
PACKAGE = REPO_ROOT / "data" / "exports" / "canonical_v1_federation"
_TS = "2026-11-17T00:00:00+00:00"
_T1 = "2026-11-10T08:00:00+00:00"
_T2 = "2026-11-12T08:00:00+00:00"
_HEADER = ("source_id", "family", "update_cadence", "pipeline_status")


def _committed_registry() -> list[dict]:
    with (REPO_ROOT / REGISTRY).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _write_registry(root: Path, rows, header=_HEADER) -> Path:
    path = root / REGISTRY
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)
    return path


def _by_ref(rows) -> dict:
    return {r["source_ref"]: r for r in rows}


# ── committed data ────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_one_row_per_registered_source_with_deterministic_ids():
    registry_ids = {r["source_id"].strip() for r in _committed_registry()}
    rows = fx.build_source_monitors(REPO_ROOT, now=_TS)
    assert len(rows) == len(registry_ids) == 167
    assert {r["source_ref"] for r in rows} == registry_ids
    for r in rows:
        assert re.fullmatch(r"mon_[a-f0-9]{32}", r["monitor_id"])
        assert r["monitor_id"] == prii_export_utils.monitor_id("moneysweep-pr", r["source_ref"])
        assert r["monitor_id"] == prii_export_utils.fid("mon", "moneysweep-pr", r["source_ref"])
    assert [r["source_ref"] for r in rows] == sorted(registry_ids)
    assert fx.build_source_monitors(REPO_ROOT, now=_TS) == rows


@pytest.mark.unit
def test_committed_rows_have_reader_shape():
    lineage = {
        "producer_script": "scripts/federation_export.py",
        "producer_phase": "SOURCE_MONITOR",
        "source_inputs": [REGISTRY],
        "extraction_method": "registry_projection",
    }
    assert not (REPO_ROOT / STATE).exists()
    for r in fx.build_source_monitors(REPO_ROOT, now=_TS):
        assert r["cadence"] in prii_export_utils.CADENCES
        assert r["declared_status"] in prii_export_utils.DECLARED_STATUSES
        assert r["last_success_basis"] in prii_export_utils.BASES
        assert r["last_success_basis"] == "NOT_RECORDED"
        assert r["last_success_at"] is None
        assert r["evidence_tier"] is None
        assert r["source_url"] is None
        assert r["name"] == r["source_ref"]
        assert r["registry_path"] == REGISTRY
        assert r["lineage"] == lineage
        assert r["synthetic"] is False
        assert r["created_at"] == r["extracted_at"] == _TS


@pytest.mark.unit
def test_committed_vocabulary_is_fully_mapped():
    # Parity guard: an unmapped value would become "unknown" here while the Hub
    # reader keeps its own table; extend both together.
    for entry in _committed_registry():
        assert entry["update_cadence"].strip().lower() in fx._MONITOR_CADENCE, entry
        assert entry["pipeline_status"].strip().lower() in fx._MONITOR_STATUS, entry


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("ad_hoc", "event"),
        ("on_drop", "event"),
        ("one_time", "static"),
        (" Weekly ", "weekly"),
        ("monthly", "monthly"),
        ("bogus", "unknown"),
        ("", "unknown"),
        (None, "unknown"),
    ],
)
def test_cadence_mapping_matches_hub(raw, expected):
    assert fx._monitor_cadence(raw) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("fully_materialized", "active"),
        ("partially_materialized", "partial"),
        ("not_materialized", "not_active"),
        (" Fully_Materialized ", "active"),
        ("no_outputs_declared", "unknown"),
        (None, "unknown"),
    ],
)
def test_status_mapping_matches_hub(raw, expected):
    assert fx._monitor_status(raw) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "cadence,window",
    [
        ("yearly", 31622400),
        ("monthly", 2678400),
        ("quarterly", 7948800),
        ("weekly", 604800),
        ("event", None),
        ("static", None),
    ],
)
def test_cadence_windows_match_hub(cadence, window):
    assert fx.MONITOR_WINDOW_SECONDS.get(cadence) == window


# ── synthetic registries ──────────────────────────────────────────────────────


def test_no_receipt_is_not_recorded(tmp_path):
    _write_registry(
        tmp_path,
        [("a", "fam", "weekly", "fully_materialized"), ("b", "fam", "ad_hoc", "not_materialized")],
    )
    rows = fx.build_source_monitors(tmp_path, now=_TS)
    assert [r["source_ref"] for r in rows] == ["a", "b"]
    for r in rows:
        assert r["last_success_basis"] == "NOT_RECORDED"
        assert r["last_success_at"] is None
        assert r["last_attempt_at"] is None
        assert r["last_attempt_status"] is None
        assert r["lineage"]["source_inputs"] == [REGISTRY]
    assert rows[0]["cadence_window_seconds"] == 604800
    assert rows[1]["cadence"] == "event" and rows[1]["cadence_window_seconds"] is None


def test_run_receipt_sets_last_success(tmp_path):
    _write_registry(
        tmp_path,
        [("a", "fam", "weekly", "fully_materialized"), ("b", "fam", "weekly", "not_materialized")],
    )
    state = tmp_path / STATE
    record_run(state, "a", "success", at=_T1)
    record_run(state, "a", "failure", at=_T2)
    rows = _by_ref(fx.build_source_monitors(tmp_path, now=_TS))
    a = rows["a"]
    assert a["last_success_basis"] == "RUN_RECEIPT"
    assert a["last_success_at"] == _T1
    assert a["last_attempt_status"] == "failure"
    assert a["last_attempt_at"] == _T2
    assert a["lineage"]["source_inputs"] == [REGISTRY, STATE]
    assert rows["b"]["last_success_basis"] == "NOT_RECORDED"


def test_failure_only_receipt_is_not_recorded(tmp_path):
    _write_registry(tmp_path, [("a", "fam", "weekly", "fully_materialized")])
    record_run(tmp_path / STATE, "a", "failure", at=_T1)
    (row,) = fx.build_source_monitors(tmp_path, now=_TS)
    assert row["last_success_basis"] == "NOT_RECORDED"
    assert row["last_success_at"] is None
    assert row["last_attempt_status"] == "failure"
    assert row["last_attempt_at"] == _T1


def test_unregistered_receipt_adds_no_row(tmp_path):
    _write_registry(tmp_path, [("a", "fam", "weekly", "fully_materialized")])
    record_run(tmp_path / STATE, "ghost", "success", at=_T1)
    rows = fx.build_source_monitors(tmp_path, now=_TS)
    assert [r["source_ref"] for r in rows] == ["a"]


def test_blank_family_is_none(tmp_path):
    _write_registry(tmp_path, [("a", "  ", "weekly", "fully_materialized")])
    (row,) = fx.build_source_monitors(tmp_path, now=_TS)
    assert row["producer_family"] is None


@pytest.mark.parametrize(
    "rows,header",
    [
        ([("a", "f", "weekly", "x"), ("a", "f", "weekly", "x")], _HEADER),
        ([(" ", "f", "weekly", "x")], _HEADER),
        ([("a", "f", "weekly")], _HEADER[:3]),
    ],
    ids=["duplicate-source-id", "empty-source-id", "missing-column"],
)
def test_bad_registry_raises(tmp_path, rows, header):
    _write_registry(tmp_path, rows, header=header)
    with pytest.raises(ValueError):
        fx.build_source_monitors(tmp_path, now=_TS)


# ── committed package ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_committed_package_lists_fresh_source_monitors():
    manifest = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
    entries = [f for f in manifest["files"] if f["stream"] == "source_monitors"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["filename"] == "source_monitors.jsonl"
    assert entry["schema_id"] == "federation_source_monitor.schema.json"
    assert entry["record_count"] == 167
    path = PACKAGE / entry["filename"]
    assert entry["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()

    committed = [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln]
    assert committed == fx.build_source_monitors(REPO_ROOT, now=manifest["created_at"]), (
        "data/exports/canonical_v1_federation/source_monitors.jsonl is stale against "
        f"{REGISTRY}: an edit to the registry CSV must re-export the committed package "
        "in the same change"
    )
    coverage = json.loads((PACKAGE / "coverage.json").read_text(encoding="utf-8"))
    assert coverage["stream_counts"]["source_monitors"] == entry["record_count"] == len(committed)


# Required properties of thehub-pr schemas/federation_source_monitor.schema.json at the
# pinned commit 0f62e4b (the schema is not vendored here; hub validate-package checks it).
_SCHEMA_REQUIRED = (
    "monitor_id",
    "source_ref",
    "name",
    "declared_status",
    "cadence",
    "last_success_basis",
    "lineage",
    "synthetic",
    "created_at",
    "extracted_at",
)


@pytest.mark.unit
def test_committed_package_rows_carry_required_fields_and_vocabulary():
    path = PACKAGE / "source_monitors.jsonl"
    committed = [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln]
    assert len(committed) == 167
    for r in committed:
        missing = [k for k in _SCHEMA_REQUIRED if k not in r]
        assert not missing, (r.get("source_ref"), missing)
        assert r["monitor_id"] == prii_export_utils.monitor_id("moneysweep-pr", r["source_ref"])
        assert r["cadence"] in prii_export_utils.CADENCES
        assert r["declared_status"] in prii_export_utils.DECLARED_STATUSES
        assert r["last_success_basis"] in prii_export_utils.BASES
        if r["last_success_basis"] == "NOT_RECORDED":
            assert r["last_success_at"] is None


@pytest.mark.unit
def test_committed_manifest_validates_against_vendored_schema():
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(
        (REPO_ROOT / "schemas" / "federation_export_manifest.schema.json").read_text(
            encoding="utf-8"
        )
    )
    manifest = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
    jsonschema.validate(manifest, schema)
