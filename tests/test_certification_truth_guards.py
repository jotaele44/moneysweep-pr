from __future__ import annotations

import ast
import copy
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tools.certification_truth_guards import (
    EvidenceError,
    aware_datetime,
    bounded_path,
    derived_execution_blockers,
    digest_json,
    evaluate_output,
    execution_state,
    freshness_status,
    load_receipts,
    receipt_binding_errors,
    release_boundary,
    strict_json,
)

pytestmark = pytest.mark.unit


def _source() -> dict:
    return {
        "source_id": "alpha", "producer_script": "scripts/alpha.py",
        "validation_threshold": {"min_rows": 1, "required_columns": ["id"]},
    }


def _output(root: Path, raw: bytes, source: dict | None = None) -> dict:
    (root / "a.csv").write_bytes(raw)
    return evaluate_output(evidence_root=root, source=source or _source(), output_path="a.csv")


@pytest.mark.parametrize("raw", [b"", b"id\n", b"id,id\n1,2\n", b"\nid\n1\n", b"id\n1,2\n",
                                 b'id\n"unterminated', b"id,name\n1\n", b"other\n1\n", b"id\n\xff\n"])
def test_invalid_csv_never_materializes(tmp_path: Path, raw: bytes) -> None:
    assert _output(tmp_path, raw)["usable"] is False


@pytest.mark.parametrize("minimum", [True, False, -1, 1.5, "1", None])
def test_malformed_minimum_is_not_silently_defaulted(tmp_path: Path, minimum: object) -> None:
    source = _source()
    source["validation_threshold"]["min_rows"] = minimum
    result = _output(tmp_path, b"id\n1\n", source)
    assert result["usable"] is False
    assert result["reason"] == "invalid_min_rows_contract"


def test_missing_schema_contract_blocks(tmp_path: Path) -> None:
    source = _source()
    del source["validation_threshold"]["required_columns"]
    assert _output(tmp_path, b"id\n1\n", source)["usable"] is False


def test_csv_preserves_raw_header_preamble_and_hash(tmp_path: Path) -> None:
    source = _source()
    source["validation_threshold"].update({
        "required_columns": [" id ", "año"], "csv": {"delimiter": ";", "header_row": 1},
    })
    raw = "preamble\n id ;año\n001;2026\n".encode()
    result = _output(tmp_path, raw, source)
    assert result["usable"] is True
    assert result["columns_raw"] == [" id ", "año"]
    assert result["sha256"] == hashlib.sha256(raw).hexdigest()
    assert result["rows"] == 1


def test_explicit_zero_minimum_is_distinct_from_empty_uncontracted_output(tmp_path: Path) -> None:
    source = _source()
    source["validation_threshold"]["min_rows"] = 0
    assert _output(tmp_path, b"id\n", source)["usable"] is True


@pytest.mark.parametrize("path", ["../x", "/x", "a/../x", "a//x", "a/./x", "C:/x", r"a\x"])
def test_unsafe_paths_are_rejected(tmp_path: Path, path: str) -> None:
    with pytest.raises(EvidenceError):
        bounded_path(tmp_path, path)


def test_symlinks_are_not_evidence(tmp_path: Path) -> None:
    (tmp_path / "original").write_text("id\n1\n")
    (tmp_path / "alias.csv").symlink_to(tmp_path / "original")
    result = evaluate_output(evidence_root=tmp_path, source=_source(), output_path="alias.csv")
    assert result["usable"] is False
    assert result["reason"] == "symlink_evidence_path"


@pytest.mark.parametrize("text", ['{"a":1,"a":2}', '{"x":NaN}', '{"x":Infinity}', '{"x":-Infinity}', '{"x":1e999}'])
def test_noncanonical_json_claims_are_rejected(text: str) -> None:
    with pytest.raises(EvidenceError):
        strict_json(text)


def test_duplicate_receipts_are_not_first_wins(tmp_path: Path) -> None:
    for name in ("a.json", "b.json"):
        (tmp_path / name).write_text('{"source_id":"alpha"}')
    with pytest.raises(EvidenceError, match="duplicate_source_receipts"):
        load_receipts(tmp_path)


def test_unclassified_receipt_files_fail_closed(tmp_path: Path) -> None:
    (tmp_path / "ignored.txt").write_text("evidence")
    with pytest.raises(EvidenceError, match="unclassified_receipt_entry"):
        load_receipts(tmp_path)


def test_malformed_receipt_is_not_silently_discarded(tmp_path: Path) -> None:
    (tmp_path / "a.json").write_text("{invalid")
    with pytest.raises(ValueError):
        load_receipts(tmp_path)


def _bound(root: Path) -> tuple[dict, dict, list[dict]]:
    source = _source()
    output = _output(root, b"id\n1\n", source)
    receipt = {
        "source_id": "alpha",
        "registry": {"source_ids_sha256": "d" * 64, "source_definition_sha256": digest_json(source)},
        "acquisition": {"producer": "scripts/alpha.py", "producer_sha": "a" * 40,
                        "completed_at": "2026-09-13T10:00:00Z"},
        "outputs": [{key: output[key] for key in ("path", "sha256", "bytes", "rows")}],
    }
    return source, receipt, [output]


def test_binding_is_from_hashes_and_definitions_not_a_receipt_flag(tmp_path: Path) -> None:
    source, receipt, outputs = _bound(tmp_path)
    assert not receipt_binding_errors(receipt=receipt, source=source,
                                      registry_digest="d" * 64, outputs=outputs)
    receipt["outputs"][0]["bytes"] = True
    assert receipt_binding_errors(receipt=receipt, source=source,
                                  registry_digest="d" * 64, outputs=outputs)


@pytest.mark.parametrize("field", ["sha256", "bytes", "rows"])
def test_each_output_identity_field_is_revalidated(tmp_path: Path, field: str) -> None:
    source, receipt, outputs = _bound(tmp_path)
    receipt["outputs"][0][field] = "forged"
    errors = receipt_binding_errors(receipt=receipt, source=source,
                                    registry_digest="d" * 64, outputs=outputs)
    assert any(field in error for error in errors)


def test_same_id_different_definition_does_not_inherit_receipt(tmp_path: Path) -> None:
    source, receipt, outputs = _bound(tmp_path)
    source["validation_threshold"]["min_rows"] = 2
    errors = receipt_binding_errors(receipt=receipt, source=source,
                                    registry_digest="d" * 64, outputs=outputs)
    assert "receipt_source_definition_mismatch" in errors


def _execution(receipt: dict) -> dict:
    return {
        "schema_version": "moneysweep.source_execution/v1", "source_id": "alpha",
        "evidence_receipt_sha256": digest_json(receipt), "producer_git_sha": "a" * 40,
        "execution_status": "SUCCESS", "started_at": "2026-09-13T09:00:00Z",
        "completed_at": "2026-09-13T10:00:00Z",
    }


def test_execution_requires_receipt_and_usable_output(tmp_path: Path) -> None:
    source, receipt, _ = _bound(tmp_path)
    kwargs = dict(receipt=receipt, source=source, receipt_errors=[],
                  as_of=datetime(2026, 9, 13, 11, tzinfo=timezone.utc))
    assert execution_state(execution=None, materialization="fully_materialized", **kwargs)[0] == "NOT_ATTEMPTED"
    assert execution_state(execution=_execution(receipt), materialization="fully_materialized", **kwargs)[0] == "EXECUTED_VALID"
    assert execution_state(execution=_execution(receipt), materialization="partially_materialized", **kwargs)[0] == "EXECUTION_UNPROVEN"


@pytest.mark.parametrize("change", [{"workflow_step_outcome": "success"}, {"producer_git_sha": "b" * 40},
                                    {"completed_at": "2027-01-01T00:00:00Z"}, {"completed_at": "2026-09-13T10:00:00"},
                                    {"execution_status": "FAILED"}, {"evidence_receipt_sha256": "c" * 64}])
def test_ci_success_or_unbound_execution_cannot_supply_credit(tmp_path: Path, change: dict) -> None:
    source, receipt, _ = _bound(tmp_path)
    execution = _execution(receipt)
    if "workflow_step_outcome" in change:
        execution = change
    else:
        execution.update(change)
    result = execution_state(execution=execution, receipt=receipt, source=source,
                             receipt_errors=[], materialization="fully_materialized",
                             as_of=datetime(2026, 9, 13, 11, tzinfo=timezone.utc))
    assert result[0] != "EXECUTED_VALID"


def test_execution_set_comparison_prevents_count_only_equivalence() -> None:
    row = {"source_id": "alpha", "automatable": True, "execution_status": "EXECUTED_VALID",
           "receipt_valid": True, "execution_blockers": [], "materialization_status": "fully_materialized"}
    assert not derived_execution_blockers({"sources": [row]}, {"alpha"})
    assert derived_execution_blockers({"sources": [row]}, {"beta"})
    assert derived_execution_blockers({"sources": [row, copy.deepcopy(row)]}, {"alpha"})


@pytest.mark.parametrize("claim", [False, True, "true", "false", 1, {"authorized": True}])
def test_legacy_activation_claim_never_authorizes(claim: object) -> None:
    result = release_boundary([], claim)
    assert result["state"] == "BLOCKED"
    assert result["production_activation_authorized"] is False
    assert result["historical_activation_claim"] == claim


def test_aware_datetimes_only() -> None:
    assert aware_datetime("2026-09-13T00:00:00") is None
    assert aware_datetime("2026-09-13T00:00:00Z") is not None


def test_scope_overwrite_and_identity_checks_remain_wired() -> None:
    root = Path(__file__).resolve().parents[1]
    engine = (root / "tools/derive_certification_truth.py").read_text()
    certifier = (root / "tools/certify_production.py").read_text()
    ast.parse(engine)
    ast.parse(certifier)
    assert "scope_dir.mkdir(parents=True, exist_ok=False)" in engine
    assert '"verified_operator_corpus_mount" if operator_corpus_id' not in engine
    assert "derived_execution_blockers(derived_truth, automatable)" in certifier
    assert "digest_json(identity) != scope_id" in certifier
    assert "release = release_boundary(" in certifier
    assert 'args.output.open("x", encoding="utf-8")' in certifier


@pytest.mark.parametrize("changes, expected", [
    ({}, "FRESH"),
    ({"sla": 0}, "FRESHNESS_UNPROVEN"),
    ({"sla": None, "cadence": "unknown"}, "FRESHNESS_UNPROVEN"),
    ({"sla": True}, "FRESHNESS_UNPROVEN"),
    ({"sla": float("inf")}, "FRESHNESS_UNPROVEN"),
    ({"basis": None}, "FRESHNESS_UNPROVEN"),
    ({"receipt_valid": False}, "FRESHNESS_UNPROVEN"),
    ({"completed_at": None}, "FRESHNESS_UNPROVEN"),
    ({"completed_at": datetime(2026, 9, 13)}, "FRESHNESS_UNPROVEN"),
    ({"completed_at": datetime(2027, 9, 13, tzinfo=timezone.utc)}, "FRESHNESS_UNPROVEN"),
    ({"completed_at": datetime(2025, 9, 13, tzinfo=timezone.utc)}, "STALE"),
    ({"cadence": "one_time", "basis": "one_time_archival", "sla": None}, "FRESHNESS_NOT_APPLICABLE"),
    ({"materialization": "partially_materialized"}, "NEVER_MATERIALIZED"),
])
def test_freshness_requires_a_bound_basis(changes: dict, expected: str) -> None:
    kwargs = dict(cadence="weekly", basis="acquisition_receipt", sla=168,
                  materialization="fully_materialized", receipt_valid=True,
                  completed_at=datetime(2026, 9, 13, 10, tzinfo=timezone.utc),
                  as_of=datetime(2026, 9, 13, 11, tzinfo=timezone.utc))
    kwargs.update(changes)
    assert freshness_status(**kwargs) == expected
