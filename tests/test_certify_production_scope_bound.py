from __future__ import annotations

from pathlib import Path

import pytest

import tools.certify_production_scope_bound as bridge

pytestmark = pytest.mark.unit


def _base_report() -> dict:
    return {
        "input_manifest": {},
        "scope": {
            "registry_total_sources": 164,
            "registry_source_ids_sha256": "d" * 64,
            "truth_scope_id": "s" * 64,
        },
        "gates": [
            {"id": "G0_SCOPE_FREEZE", "state": "PASS", "evidence": {}, "blockers": []},
            {
                "id": "G8_PROVENANCE_AND_LINEAGE",
                "state": "BLOCKED",
                "evidence": {
                    "historical_operator_authority_claim": True,
                    "coverage_audit_total_sources": 162,
                    "coverage_audit_orphan_rows": None,
                },
                "blockers": ["scope_bound_corpus_reverification_unimplemented"],
            },
            {
                "id": "G9_CANONICAL_MASTER_INVARIANTS",
                "state": "BLOCKED",
                "evidence": {},
                "blockers": ["scope_bound_canonical_replay_unimplemented"],
            },
            {
                "id": "G11_PRODUCTION_EXPORT_AND_FEDERATION",
                "state": "BLOCKED",
                "evidence": {},
                "blockers": ["scope_bound_federation_replay_unimplemented"],
            },
            {
                "id": "G12_RELEASE_CERTIFICATION",
                "state": "BLOCKED",
                "evidence": {"historical_activation_claim": True},
                "blockers": ["G8_PROVENANCE_AND_LINEAGE"],
            },
        ],
        "certification_state": "NON_PRODUCTION_DIAGNOSTIC",
        "production_eligible": False,
        "nonpass_gate_ids": [
            "G8_PROVENANCE_AND_LINEAGE",
            "G9_CANONICAL_MASTER_INVARIANTS",
            "G11_PRODUCTION_EXPORT_AND_FEDERATION",
            "G12_RELEASE_CERTIFICATION",
        ],
    }


def _gates(report: dict) -> dict[str, dict]:
    return {gate["id"]: gate for gate in report["gates"]}


def test_live_scope_bound_reverification_can_close_g8_without_closing_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bridge, "build_base_report", lambda **_: _base_report())
    monkeypatch.setattr(
        bridge,
        "_load_truth_scope",
        lambda _: {"scope_identity": {"operator_corpus_id": "c" * 64}},
    )
    monkeypatch.setattr(
        bridge,
        "verify_scope_bound_operator_corpus",
        lambda **_: {
            "authoritative": True,
            "blockers": [],
            "corpus_root": str(tmp_path / "corpus"),
            "scope_operator_corpus_id": "c" * 64,
            "corpus_id": "c" * 64,
            "computed_corpus_id": "c" * 64,
            "registry": {"total_sources": 164, "source_ids_sha256": "d" * 64},
            "processed_file_inventory": {
                "orphan_mounted_files": [],
                "unreceipted_operator_files": [],
                "accounted_outputs_missing_from_operator": [],
            },
            "manifest_source_count": 164,
            "manifest_product_count": 3,
            "verification_scope": {
                "operator_snapshot_required": True,
                "mode": "full_operator_snapshot",
            },
            "verification_errors": [],
        },
    )

    report = bridge.build_report(
        root=tmp_path,
        truth_root=tmp_path / "scope",
        operator_corpus_root=tmp_path / "corpus",
    )
    gates = _gates(report)

    assert gates["G8_PROVENANCE_AND_LINEAGE"]["state"] == "PASS"
    assert gates["G8_PROVENANCE_AND_LINEAGE"]["blockers"] == []
    assert gates["G8_PROVENANCE_AND_LINEAGE"]["evidence"][
        "historical_operator_authority_claim"
    ] is True
    assert gates["G8_PROVENANCE_AND_LINEAGE"]["evidence"][
        "historical_coverage_audit_total_sources"
    ] == 162
    assert gates["G12_RELEASE_CERTIFICATION"]["state"] == "BLOCKED"
    assert "G8_PROVENANCE_AND_LINEAGE" not in gates["G12_RELEASE_CERTIFICATION"]["blockers"]
    assert "G9_CANONICAL_MASTER_INVARIANTS" in gates["G12_RELEASE_CERTIFICATION"]["blockers"]
    assert "G11_PRODUCTION_EXPORT_AND_FEDERATION" in gates["G12_RELEASE_CERTIFICATION"]["blockers"]
    assert "production_activation_not_authorized" in gates["G12_RELEASE_CERTIFICATION"]["blockers"]
    assert report["certification_state"] == "NON_PRODUCTION_DIAGNOSTIC"
    assert report["production_eligible"] is False


def test_g8_remains_blocked_when_live_reverification_is_not_authoritative(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bridge, "build_base_report", lambda **_: _base_report())
    monkeypatch.setattr(
        bridge,
        "_load_truth_scope",
        lambda _: {"scope_identity": {"operator_corpus_id": "c" * 64}},
    )
    monkeypatch.setattr(
        bridge,
        "verify_scope_bound_operator_corpus",
        lambda **_: {
            "authoritative": False,
            "blockers": ["truth_scope_operator_corpus_id_mismatch"],
            "corpus_root": str(tmp_path / "corpus"),
            "scope_operator_corpus_id": "e" * 64,
            "corpus_id": "c" * 64,
            "computed_corpus_id": "c" * 64,
            "registry": {"total_sources": 164, "source_ids_sha256": "d" * 64},
            "processed_file_inventory": {},
            "manifest_source_count": 164,
            "manifest_product_count": 3,
            "verification_scope": {
                "operator_snapshot_required": True,
                "mode": "full_operator_snapshot",
            },
            "verification_errors": [],
        },
    )

    report = bridge.build_report(
        root=tmp_path,
        truth_root=tmp_path / "scope",
        operator_corpus_root=tmp_path / "corpus",
    )
    gate = _gates(report)["G8_PROVENANCE_AND_LINEAGE"]

    assert gate["state"] == "BLOCKED"
    assert gate["evidence"]["operator_corpus_authoritative"] is False
    assert gate["blockers"] == ["truth_scope_operator_corpus_id_mismatch"]


def test_scope_freeze_failure_blocks_g8_even_if_corpus_verifier_returns_authoritative(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _base_report()
    base["gates"][0]["state"] = "FAIL"
    monkeypatch.setattr(bridge, "build_base_report", lambda **_: base)
    monkeypatch.setattr(bridge, "_load_truth_scope", lambda _: {})
    monkeypatch.setattr(
        bridge,
        "verify_scope_bound_operator_corpus",
        lambda **_: {
            "authoritative": True,
            "blockers": [],
            "corpus_root": str(tmp_path / "corpus"),
            "verification_scope": {
                "operator_snapshot_required": True,
                "mode": "full_operator_snapshot",
            },
        },
    )

    report = bridge.build_report(
        root=tmp_path,
        truth_root=tmp_path / "scope",
        operator_corpus_root=tmp_path / "corpus",
    )
    gate = _gates(report)["G8_PROVENANCE_AND_LINEAGE"]

    assert gate["state"] == "BLOCKED"
    assert "scope_freeze_not_pass" in gate["blockers"]
