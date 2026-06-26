"""Unit tests for the security-sensitive pipeline modules (Wave G, PR 6).

These four modules gate how external/manual source files get materialized into
the staging tree, so their validation primitives — forbidden-artifact-token
detection, status/type gates, approved-stage-path enforcement, and credential
checks — are the security surface and are exercised directly here:

  - moneysweep.pipeline.credentialed_endpoint_execution
  - moneysweep.pipeline.manual_import_dropzone
  - moneysweep.pipeline.source_materialization
  - moneysweep.pipeline.scoped_unfreeze_materialization

All behavior asserted here was verified against the live implementation. No
network or real credentials are used; producer "scripts" are tiny tmp files.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

import pytest

from moneysweep.pipeline import (
    credentialed_endpoint_execution as cee,
    manual_import_dropzone as mid,
    scoped_unfreeze_materialization as suf,
    source_materialization as sm,
)

# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #


def _write_csv(path: Path, rows: list[dict], cols: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------- #
# manual_import_dropzone — pure helpers
# --------------------------------------------------------------------------- #


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw,expected",
    [(None, 0), ("", 0), ("3x", 0), ("3.5", 3), ("  42  ", 42), ("7", 7), (True, 0)],
)
def test_safe_int(raw, expected):
    assert mid.safe_int(raw) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, []),
        ("", []),
        ("a|b|c", ["a", "b", "c"]),
        ("a||b", ["a", "b"]),
        (" a | b ", ["a", "b"]),
    ],
)
def test_split_pipe(raw, expected):
    assert mid.split_pipe(raw) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "text,expected",
    [
        (None, False),
        ("", False),
        ("clean_input", False),
        ("REPORT", True),
        ("reports", True),  # substring match
        ("power_network_map", True),
        ("dominance_score", True),
    ],
)
def test_contains_forbidden_token(text, expected):
    assert mid.contains_forbidden_token(text) is expected


@pytest.mark.unit
def test_forbidden_token_set_is_the_documented_set():
    # This is the security allowlist's complement; lock it so a silent edit
    # (dropping "network", say) is caught.
    assert mid.FORBIDDEN_ARTIFACT_TOKENS == (
        "report",
        "summary",
        "graph",
        "network",
        "top_nodes",
        "top_node",
        "power_network",
        "dominance",
        "risk_alert",
        "investigative",
    )


@pytest.mark.unit
def test_read_json_tolerates_missing_and_malformed(tmp_path):
    assert mid.read_json(tmp_path / "absent.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert mid.read_json(bad) == {}
    notdict = tmp_path / "list.json"
    notdict.write_text("[1, 2]", encoding="utf-8")
    assert mid.read_json(notdict) == {}


@pytest.mark.unit
def test_write_then_read_json_roundtrips(tmp_path):
    p = tmp_path / "nested" / "out.json"
    mid.write_json(p, {"b": 1, "a": 2})
    assert mid.read_json(p) == {"b": 1, "a": 2}


@pytest.mark.unit
def test_sha256_file_and_record_count(tmp_path):
    p = tmp_path / "d.csv"
    p.write_text("col\n1\n2\n", encoding="utf-8")
    assert mid.sha256_file(p) == _sha(p)
    assert mid.record_count(p) == 2  # two data rows
    assert mid.sha256_file(tmp_path / "absent") == ""
    assert mid.record_count(tmp_path / "absent") == 0


# --------------------------------------------------------------------------- #
# manual_import_dropzone — process_manual_import_dropzones entry point
# --------------------------------------------------------------------------- #


def _manual_row(**over) -> dict:
    base = {
        "priority": "1",
        "expected_input": "usaspend_pr",
        "source_family": "usaspending",
        "target_dropzone_path": "data/manual_import_dropzone",
        "target_output_path": "data/staging/processed/out.csv",
        "accepted_filename_patterns": "*.csv",
        "required_columns": "Award ID|Recipient Name",
        "producer_script": "manual",
    }
    base.update(over)
    return base


@pytest.mark.unit
def test_manual_dropzone_empty_is_noop(tmp_project):
    inv, still, manifests, metrics, forbidden = mid.process_manual_import_dropzones(
        tmp_project, manual_rows=[]
    )
    assert inv == [] and still == [] and manifests == []
    assert metrics["manual_sources_checked"] == 0
    assert forbidden is False


@pytest.mark.unit
def test_manual_dropzone_happy_path_stages_and_manifests(tmp_project):
    dz = tmp_project / "data" / "manual_import_dropzone"
    dz.mkdir(parents=True, exist_ok=True)
    (dz / "awards.csv").write_text("Award ID,Recipient Name\n123,ABC Corp\n", encoding="utf-8")

    inv, still, manifests, metrics, forbidden = mid.process_manual_import_dropzones(
        tmp_project, manual_rows=[_manual_row()]
    )
    assert forbidden is False
    assert inv[0]["review_status"] == "validated_and_staged"
    assert inv[0]["manual_file_validated"] is True
    assert len(manifests) == 1
    assert metrics["manual_files_validated"] == 1
    # The staged target now exists in the approved processed/ tree.
    assert (tmp_project / "data" / "staging" / "processed" / "out.csv").exists()


@pytest.mark.unit
def test_manual_dropzone_missing_dir_is_still_required(tmp_project):
    inv, still, manifests, metrics, forbidden = mid.process_manual_import_dropzones(
        tmp_project,
        manual_rows=[_manual_row(target_dropzone_path="data/manual_import_dropzone/none")],
    )
    assert inv[0]["review_status"] == "pending_manual_file"
    assert inv[0]["failure_reason"] in {"dropzone_missing", "no_file_present", "pattern_mismatch"}
    assert len(still) == 1
    assert metrics["manual_files_validated"] == 0


@pytest.mark.unit
def test_manual_dropzone_missing_required_columns_rejected(tmp_project):
    dz = tmp_project / "data" / "manual_import_dropzone"
    dz.mkdir(parents=True, exist_ok=True)
    (dz / "awards.csv").write_text("Award ID,Recipient Name\n123,ABC\n", encoding="utf-8")

    inv, _still, _m, _metrics, _f = mid.process_manual_import_dropzones(
        tmp_project,
        manual_rows=[_manual_row(required_columns="Award ID|Recipient Name|MISSING_COL")],
    )
    assert inv[0]["manual_file_validated"] is False
    assert inv[0]["failure_reason"].startswith("missing_required_columns")
    assert "MISSING_COL" in inv[0]["failure_reason"]


@pytest.mark.unit
def test_manual_dropzone_forbidden_token_flagged(tmp_project):
    _inv, _still, _m, _metrics, forbidden = mid.process_manual_import_dropzones(
        tmp_project, manual_rows=[_manual_row(expected_input="power_network_report")]
    )
    assert forbidden is True


# --------------------------------------------------------------------------- #
# credentialed_endpoint_execution
# --------------------------------------------------------------------------- #


@pytest.mark.unit
@pytest.mark.parametrize(
    "text,expected",
    [(None, ""), ("", ""), ("a\n\nb   c", "a b c"), ("abcdef", "abcdef")],
)
def test_stderr_excerpt_safe_collapses_whitespace(text, expected):
    assert cee._stderr_excerpt_safe(text) == expected


@pytest.mark.unit
def test_stderr_excerpt_safe_truncates(tmp_path):
    assert cee._stderr_excerpt_safe("abcdef", 3) == "abc"


@pytest.mark.unit
def test_run_command_rejects_empty_command(tmp_path):
    ok, code, excerpt = cee._run_command(tmp_path, "   ", timeout_s=5)
    assert ok is False and code == 1
    assert "missing command" in excerpt


@pytest.mark.unit
def test_read_script_required_env_vars_finds_getenv_usages(tmp_path):
    script = tmp_path / "scripts" / "p.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        "import os\n"
        'os.getenv("API_KEY")\n'
        'os.environ.get("TOKEN")\n'
        'os.environ["API_KEY"]\n',  # duplicate -> deduped
        encoding="utf-8",
    )
    names = cee._read_script_required_env_vars(tmp_path, "scripts/p.py")
    assert names == ["API_KEY", "TOKEN"]
    # Missing script -> no required vars (not an error).
    assert cee._read_script_required_env_vars(tmp_path, "scripts/absent.py") == []


@pytest.mark.unit
def test_evaluate_credential_requests_empty(tmp_project):
    evals, missing, by_input, n_avail, n_missing, forbidden = cee.evaluate_credential_requests(
        tmp_project, credential_request_rows=[]
    )
    assert evals == [] and missing == [] and by_input == {}
    assert n_avail == 0 and n_missing == 0 and forbidden is False


@pytest.mark.unit
def test_evaluate_credential_requests_flags_missing_env(tmp_project, monkeypatch):
    monkeypatch.delenv("UNSET_CRED_XYZ", raising=False)
    script = tmp_project / "scripts" / "needs_cred.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text('import os\nos.getenv("UNSET_CRED_XYZ")\n', encoding="utf-8")

    rows = [
        {"priority": "1", "expected_input": "clean_src", "producer_script": "scripts/needs_cred.py"}
    ]
    evals, missing, _by, n_avail, n_missing, forbidden = cee.evaluate_credential_requests(
        tmp_project, credential_request_rows=rows
    )
    # missing_env_vars is pipe-joined for CSV emission, not a Python list.
    assert evals[0]["missing_env_vars"] == "UNSET_CRED_XYZ"
    assert evals[0]["credentials_available"] is False
    assert n_avail == 0 and n_missing == 1 and forbidden is False
    assert missing[0]["review_status"] == "pending_credentials"


@pytest.mark.unit
def test_evaluate_credential_requests_satisfied_when_env_present(tmp_project, monkeypatch):
    monkeypatch.setenv("PRESENT_CRED_XYZ", "secret-value")
    script = tmp_project / "scripts" / "has_cred.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text('import os\nos.getenv("PRESENT_CRED_XYZ")\n', encoding="utf-8")

    rows = [
        {"priority": "1", "expected_input": "clean_src", "producer_script": "scripts/has_cred.py"}
    ]
    evals, _missing, _by, n_avail, n_missing, _f = cee.evaluate_credential_requests(
        tmp_project, credential_request_rows=rows
    )
    assert evals[0]["credentials_available"] is True
    assert evals[0]["missing_env_vars"] == ""
    assert n_avail == 1 and n_missing == 0


@pytest.mark.unit
def test_evaluate_credential_requests_forbidden_artifact_flag(tmp_project):
    rows = [{"priority": "1", "expected_input": "network_dump", "producer_script": ""}]
    _evals, _missing, _by, _na, _nm, forbidden = cee.evaluate_credential_requests(
        tmp_project, credential_request_rows=rows
    )
    assert forbidden is True


# --------------------------------------------------------------------------- #
# source_materialization
# --------------------------------------------------------------------------- #

_INV_COLS = [
    "target_output_path",
    "source_file",
    "manifest_path",
    "row_count",
    "sha256",
    "validation_status",
    "manifest_type",
    "source_system",
    "producer_script",
]


@pytest.mark.unit
@pytest.mark.parametrize(
    "value,expected",
    [
        ("", False),
        ("pending", False),
        ("Valid", True),
        ("validated_and_staged", True),
        ("ok", True),
        ("success", True),
    ],
)
def test_status_is_validated(value, expected):
    assert sm._status_is_validated(value) is expected


@pytest.mark.unit
def test_manifest_type_valid_is_case_insensitive_exact():
    assert sm._manifest_type_valid("validated_source_manifest") is True
    assert sm._manifest_type_valid("VALIDATED_SOURCE_MANIFEST") is True
    assert sm._manifest_type_valid("other") is False


@pytest.mark.unit
def test_is_approved_stage_path_enforces_staging_prefixes(tmp_path):
    good = tmp_path / "data" / "staging" / "processed" / "x.csv"
    good.parent.mkdir(parents=True, exist_ok=True)
    good.write_text("c\n1\n", encoding="utf-8")
    bad = tmp_path / "data" / "other" / "y.csv"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("c\n1\n", encoding="utf-8")
    assert sm._is_approved_stage_path(good, [tmp_path]) is True
    assert sm._is_approved_stage_path(bad, [tmp_path]) is False
    assert sm.APPROVED_STAGE_PREFIXES == (
        "data/staging/processed/",
        "data/staging/expansion/",
    )


@pytest.mark.unit
def test_resolve_abs_and_relative_posix_roundtrip(tmp_path):
    assert sm._resolve_abs(tmp_path, "/abs/path") == Path("/abs/path")
    rel = sm._resolve_abs(tmp_path, "a/b")
    assert rel.as_posix().endswith("/a/b")
    f = tmp_path / "data" / "staging" / "processed" / "x.csv"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("c\n1\n", encoding="utf-8")
    assert sm._relative_posix(tmp_path, f) == "data/staging/processed/x.csv"


@pytest.mark.unit
def test_record_from_manifest_validity_and_forbidden_flags(tmp_path):
    valid = sm._record_from_manifest(
        tmp_path,
        {
            "target_output_path": "data/staging/processed/x.csv",
            "source_file": "data/staging/processed/x.csv",
            "manifest_path": "m.json",
            "row_count": "5",
            "sha256": "ABC",  # stored lowercased
            "validation_status": "validated",
            "manifest_type": "validated_source_manifest",
            "source_system": "ts",
            "producer_script": "p.py",
        },
    )
    assert valid["is_manifest_valid"] is True
    assert valid["is_forbidden"] is False
    assert valid["sha256"] == "abc"

    invalid = sm._record_from_manifest(
        tmp_path,
        {
            "target_output_path": "data/x/report.csv",  # forbidden token + bad row_count
            "source_file": "f",
            "manifest_path": "m",
            "row_count": "0",
            "sha256": "",
            "validation_status": "pending",
            "manifest_type": "other",
            "source_system": "",
            "producer_script": "",
        },
    )
    assert invalid["is_manifest_valid"] is False
    assert invalid["is_forbidden"] is True


@pytest.mark.unit
def test_source_materialization_empty_inventory(tmp_project):
    status = sm.run_source_materialization(tmp_project)
    assert status["r4_9b_manifest_records_checked"] == 0
    assert status["r4_9b_materialization_blockers"] == 0
    # Diagnostic invariants the module always asserts.
    assert status["phase_7_8_blocked"] is True
    assert status["production_status"] == "NON_PRODUCTION_DIAGNOSTIC"


@pytest.mark.integration
def test_source_materialization_happy_path_materializes_and_hash_validates(tmp_project):
    src = tmp_project / "data" / "staging" / "processed" / "src.csv"
    src.write_text("col\n1\n2\n3\n", encoding="utf-8")
    inv = tmp_project / "data" / "exports" / "validated_source_manifest_inventory_r4_8i.csv"
    _write_csv(
        inv,
        [
            {
                "target_output_path": "data/staging/processed/src.csv",
                "source_file": "data/staging/processed/src.csv",
                "manifest_path": "data/manifests/m.json",
                "row_count": "3",
                "sha256": _sha(src),
                "validation_status": "validated",
                "manifest_type": "validated_source_manifest",
                "source_system": "ts",
                "producer_script": "scripts/x.py",
            }
        ],
        _INV_COLS,
    )
    status = sm.run_source_materialization(tmp_project)
    assert status["r4_9b_manifest_records_checked"] == 1
    assert status["r4_9b_files_materialized"] == 1
    assert status["r4_9b_files_hash_validated"] == 1
    assert status["r4_9b_materialization_blockers"] == 0


@pytest.mark.integration
def test_source_materialization_forbidden_path_blocks(tmp_project):
    inv = tmp_project / "data" / "exports" / "validated_source_manifest_inventory_r4_8i.csv"
    _write_csv(
        inv,
        [
            {
                "target_output_path": "data/staging/processed/network_map.csv",
                "source_file": "data/staging/processed/network_map.csv",
                "manifest_path": "data/manifests/m.json",
                "row_count": "3",
                "sha256": "deadbeef",
                "validation_status": "validated",
                "manifest_type": "validated_source_manifest",
                "source_system": "ts",
                "producer_script": "s.py",
            }
        ],
        _INV_COLS,
    )
    status = sm.run_source_materialization(tmp_project)
    assert status["r4_9b_forbidden_artifact_usage"] is True
    assert status["r4_9b_materialization_blockers"] == 1
    assert status["r4_9b_files_materialized"] == 0


@pytest.mark.integration
def test_source_materialization_invalid_manifest_blocks(tmp_project):
    inv = tmp_project / "data" / "exports" / "validated_source_manifest_inventory_r4_8i.csv"
    _write_csv(
        inv,
        [
            {
                "target_output_path": "data/staging/processed/src.csv",
                "source_file": "data/staging/processed/src.csv",
                "manifest_path": "data/manifests/m.json",
                "row_count": "0",  # invalid
                "sha256": "",
                "validation_status": "pending",
                "manifest_type": "other",
                "source_system": "ts",
                "producer_script": "s.py",
            }
        ],
        _INV_COLS,
    )
    status = sm.run_source_materialization(tmp_project)
    assert status["r4_9b_files_materialized"] == 0
    assert status["r4_9b_materialization_blockers"] == 1
    blockers = tmp_project / "data" / "review_queue" / "source_materialization_blockers_r4_9b.csv"
    reason = list(csv.DictReader(blockers.open(encoding="utf-8")))[0]["blocker_reason"]
    assert reason == "invalid_manifest_record"


# --------------------------------------------------------------------------- #
# scoped_unfreeze_materialization
# --------------------------------------------------------------------------- #

_CAND_COLS = [
    "expected_input",
    "source_family",
    "blocker_class",
    "candidate_path",
    "candidate_relpath",
    "candidate_sha256",
    "unfreeze_condition",
    "validation_command",
]


@pytest.mark.unit
@pytest.mark.parametrize(
    "value,expected",
    [
        (None, False),
        ("", False),
        ("True", True),
        ("YES", True),
        ("1", True),
        ("y", False),
        ("0", False),
    ],
)
def test_truthy(value, expected):
    assert suf._truthy(value) is expected


@pytest.mark.unit
def test_manifest_relpath_sanitizes_name():
    rel = suf._manifest_relpath(3, Path("/z/data/staging/processed/foo.csv"))
    assert rel == "data/manifests/r4_9g/03_foo.csv.manifest.json"


@pytest.mark.unit
def test_approved_target_match_rules():
    row = {
        "target_output_path": "data/staging/processed/out.csv",
        "target_dropzone_path": "data/dz",
    }
    assert (
        suf._approved_target_match(
            candidate_relpath="data/staging/processed/out.csv", expected_input="src", checklist=row
        )
        is True
    )
    assert (
        suf._approved_target_match(
            candidate_relpath="data/dz/file.csv", expected_input="src", checklist=row
        )
        is True
    )  # dropzone prefix
    assert (
        suf._approved_target_match(candidate_relpath="src", expected_input="src", checklist=row)
        is True
    )  # expected_input exact
    assert (
        suf._approved_target_match(
            candidate_relpath="data/elsewhere/x.csv", expected_input="src", checklist=row
        )
        is False
    )
    assert (
        suf._approved_target_match(candidate_relpath="x", expected_input="y", checklist={}) is False
    )


@pytest.mark.unit
def test_blocked_rows_from_r49f_tags_each_origin():
    blocked = suf._blocked_rows_from_r49f(
        generated_at="T",
        still_missing_rows=[{"expected_input": "a", "missing_reason": "no_delivery"}],
        rejected_rows=[{"expected_input": "b", "validation_reason": "bad"}],
    )
    by_input = {r["expected_input"]: r for r in blocked}
    assert by_input["a"]["r4_9g_status"] == "still_blocked_from_r4_9f"
    assert by_input["a"]["blocker_reason"] == "no_delivery"
    assert by_input["b"]["r4_9g_status"] == "r4_9g_candidate_rejected"
    assert by_input["b"]["blocker_reason"] == "bad"


@pytest.mark.unit
def test_scoped_unfreeze_no_candidates_does_not_pass_gate(tmp_project):
    status = suf.run_scoped_unfreeze_materialization(tmp_project)
    assert status["r4_9g_candidates_loaded"] == 0
    assert status["r4_9g_gate_passed"] is False  # gate requires >0 candidates


@pytest.mark.integration
def test_scoped_unfreeze_forbidden_candidate_rejected(tmp_project):
    cand = tmp_project / "data" / "review_queue" / "unfreeze_candidates_r4_9f.csv"
    _write_csv(
        cand,
        [{"expected_input": "src", "candidate_relpath": "data/staging/processed/network_x.csv"}],
        _CAND_COLS,
    )
    status = suf.run_scoped_unfreeze_materialization(tmp_project)
    assert status["r4_9g_forbidden_artifact_usage"] is True
    assert status["r4_9g_candidates_rejected"] == 1
    report = tmp_project / "data" / "exports" / "scoped_unfreeze_validation_report_r4_9g.csv"
    rows = list(csv.DictReader(report.open(encoding="utf-8")))
    assert rows[0]["validation_status"] == "rejected"
    assert rows[0]["validation_reason"] == "candidate_forbidden_artifact_path"


@pytest.mark.integration
def test_scoped_unfreeze_candidate_not_in_checklist_rejected(tmp_project):
    cand = tmp_project / "data" / "review_queue" / "unfreeze_candidates_r4_9f.csv"
    _write_csv(
        cand,
        [
            {
                "expected_input": "unknown_src",
                "candidate_relpath": "data/staging/processed/clean.csv",
            }
        ],
        _CAND_COLS,
    )
    status = suf.run_scoped_unfreeze_materialization(tmp_project)
    assert status["r4_9g_candidates_rejected"] == 1
    report = tmp_project / "data" / "exports" / "scoped_unfreeze_validation_report_r4_9g.csv"
    rows = list(csv.DictReader(report.open(encoding="utf-8")))
    assert rows[0]["validation_reason"] == "candidate_not_listed_in_source_delivery_checklist"
