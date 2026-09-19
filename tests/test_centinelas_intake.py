"""Tests for the Centinelas → MoneySweep pre-official located-finance intake."""

from __future__ import annotations

import json
from pathlib import Path


from moneysweep.runtime.centinelas_intake import (
    ingest_centinelas_drops,
    is_finance_relevant,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _drop(intake_dir: Path, item_id: str, **overrides) -> None:
    payload = {
        "schema_version": "1.0",
        "item_id": item_id,
        "source_url": f"https://example.com/{item_id}",
        "source_name": "Test",
        "title": "Public matter",
        "body_text": "",
        "labels": ["FINANCIAL"],
        "captured_at": "2026-07-01T00:00:00+00:00",
        "published_at": "2026-07-01T00:00:00+00:00",
        "evidence_tier": "T3",
    }
    payload.update(overrides)
    (intake_dir / f"{item_id}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_is_finance_relevant():
    assert is_finance_relevant({"labels": ["FINANCIAL"]})
    assert is_finance_relevant({"labels": ["POLITICAL", "GEO_GEOLOGY"]})
    assert not is_finance_relevant({"labels": ["ENVIRONMENTAL"]})
    assert not is_finance_relevant({"labels": []})


def test_signal_id_fallback_preserves_centinalas_identity(tmp_path):
    intake = tmp_path / "intake"
    intake.mkdir()
    payload = {
        "signal_id": "CENT-SIG-real-001",
        "source_url": "https://example.com/real",
        "title": "Finance signal",
        "labels": ["FINANCIAL"],
        "captured_at": "2026-07-01T00:00:00+00:00",
        "published_at": "2026-07-01T00:00:00+00:00",
        "evidence_tier": "T1",
        "is_synthetic": False,
    }
    (intake / "CENT-SIG-real-001.json").write_text(json.dumps(payload), encoding="utf-8")
    result = ingest_centinelas_drops(intake, root=REPO_ROOT)
    assert result["count"] == 1
    assert result["awards"][0]["centinelas_item_id"] == "CENT-SIG-real-001"
    assert result["awards"][0]["award_id"] == "CS-CENT-CENT-SIG-real-001"


def test_no_files(tmp_path):
    result = ingest_centinelas_drops(tmp_path / "intake", root=REPO_ROOT)
    assert result["status"] == "NO_FILES"
    assert result["awards"] == []


def test_finance_drop_becomes_located_candidate(tmp_path):
    intake = tmp_path / "intake"
    intake.mkdir()
    _drop(
        intake,
        "fin001",
        municipalities=["Ponce"],
        agencies=["Autoridad de Acueductos y Alcantarillados"],
        estimated_value=1500000.0,
        signal_stage="rfp_open",
        beat="contracts",
    )
    # A non-finance drop must be ignored.
    _drop(intake, "env001", labels=["ENVIRONMENTAL"])

    result = ingest_centinelas_drops(intake, root=REPO_ROOT)
    assert result["status"] == "OK"
    assert result["count"] == 1
    award = result["awards"][0]
    assert award["award_id"] == "CS-CENT-fin001"
    assert award["amount"] == 1500000.0
    assert award["source_id"] == "centinelas-pr"
    assert award["signal_stage"] == "rfp_open"
    assert award["synthetic"] is False
    loc = award["location"]
    assert loc["municipality_name"] == "Ponce"
    assert loc["municipality_code"].startswith("72")
    assert loc["attribution_source"] == "centinelas_signal"


def test_municipality_derived_from_title_when_absent(tmp_path):
    intake = tmp_path / "intake"
    intake.mkdir()
    _drop(
        intake,
        "fin002",
        title="Nuevo contrato municipal en Mayaguez para infraestructura",
        estimated_value=None,
    )
    result = ingest_centinelas_drops(intake, root=REPO_ROOT)
    assert result["count"] == 1
    award = result["awards"][0]
    # amount degrades to 0.0 when estimated_value is null; location still resolves.
    assert award["amount"] == 0.0
    assert award["location"]["municipality_name"] == "Mayaguez"  # canonical English form
    assert award["location"]["municipality_code"] == "72097"


def test_recipient_distinct_from_funder(tmp_path):
    intake = tmp_path / "intake"
    intake.mkdir()
    _drop(
        intake,
        "fin004",
        title="Del Valle Group awarded Camp Santiago contract",
        recipients=["Del Valle Group"],
        agencies=["Puerto Rico National Guard"],
        estimated_value=299700000.0,
    )
    result = ingest_centinelas_drops(intake, root=REPO_ROOT)
    award = result["awards"][0]
    # Awardee and awarding agency must be carried as distinct values.
    assert award["recipient_entity_id"] == "Del Valle Group"
    assert award["funding_agency_entity_id"] == "Puerto Rico National Guard"
    assert award["recipient_entity_id"] != award["funding_agency_entity_id"]


def test_recipient_falls_back_to_agency_when_absent(tmp_path):
    intake = tmp_path / "intake"
    intake.mkdir()
    _drop(intake, "fin005", agencies=["Autoridad de Carreteras"])
    result = ingest_centinelas_drops(intake, root=REPO_ROOT)
    award = result["awards"][0]
    # No recipient extracted → preserve prior behavior (recipient == agency).
    assert award["recipient_entity_id"] == "Autoridad de Carreteras"
    assert award["funding_agency_entity_id"] == "Autoridad de Carreteras"


def test_unresolved_location_degrades_gracefully(tmp_path):
    intake = tmp_path / "intake"
    intake.mkdir()
    _drop(intake, "fin003", title="Statewide fiscal note", body_text="no municipality here")
    result = ingest_centinelas_drops(intake, root=REPO_ROOT)
    assert result["count"] == 1
    loc = result["awards"][0]["location"]
    assert loc["municipality_code"] == ""
    assert loc["attribution_confidence"] == "unknown"
