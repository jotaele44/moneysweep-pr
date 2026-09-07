from pathlib import Path

from scripts import audit_hud_drgr_authorized_sources as audit


def test_hcv_is_not_promoted_to_authorized_drgr(tmp_path, monkeypatch):
    source = tmp_path / "pr_hud_hcv.csv"
    source.write_text("Program,Count\nHCV,2\n", encoding="utf-8")
    monkeypatch.setattr(audit, "KNOWN_PATHS", [source])

    receipt = audit.build_receipt(tmp_path / "receipt")

    assert receipt["result_state"] == "PARTIAL_UNRESOLVED"
    assert receipt["records"][0]["classification"] == "PARTIAL_NOT_AUTHORIZED_DRGR"


def test_non_empty_activity_csv_is_candidate_not_certified(tmp_path, monkeypatch):
    source = tmp_path / "HUD_DRGR_activity_export.csv"
    source.write_text("Activity ID,Activity Name,Grant Number\nA-1,Water repair,B-18-DP-72\n", encoding="utf-8")
    monkeypatch.setattr(audit, "KNOWN_PATHS", [source])

    receipt = audit.build_receipt(tmp_path / "receipt")

    assert receipt["result_state"] == "FOUND_AUTHORIZED_CANDIDATE"
    assert receipt["records"][0]["inclusion_decision"] == "eligible_for_hud_drgr_ingest_review"
