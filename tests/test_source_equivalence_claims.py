from __future__ import annotations

from pathlib import Path

import pytest

from tools.verify_source_equivalence_claims import build_report

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[1]


def _by_source(report: dict) -> dict[str, dict]:
    return {str(claim["source_id"]): claim for claim in report["claims"]}


def test_current_equivalence_claim_set_is_evidence_valid_but_non_promoting() -> None:
    report = build_report(root=ROOT)
    claims = _by_source(report)

    assert report["claim_set_valid"] is True
    assert report["claim_errors"] == []
    assert report["claim_count"] == 2
    assert report["certified_equivalent_count"] == 0
    assert report["non_certifying_claim_count"] == 2
    assert report["policy"]["silent_substitution_allowed"] is False
    assert report["policy"]["substitution_requires_certified_equivalent"] is True

    assert set(claims) == {"prasa", "hud_drgr_authorized"}
    assert claims["prasa"]["decision"] == "PARTIAL_EQUIVALENCE"
    assert claims["prasa"]["certified_equivalent"] is False
    assert claims["prasa"]["claim_evidence_valid"] is True
    assert claims["prasa"]["verified_evidence_count"] == 1
    assert claims["prasa"]["evidence_count"] == 1

    assert claims["hud_drgr_authorized"]["decision"] == "UNPROVEN"
    assert claims["hud_drgr_authorized"]["certified_equivalent"] is False
    assert claims["hud_drgr_authorized"]["claim_evidence_valid"] is True
    assert claims["hud_drgr_authorized"]["verified_evidence_count"] == 1
    assert claims["hud_drgr_authorized"]["evidence_count"] == 1


def test_claim_set_digest_is_deterministic() -> None:
    first = build_report(root=ROOT)
    second = build_report(root=ROOT)

    assert first == second
    assert len(first["claim_set_sha256"]) == 64
