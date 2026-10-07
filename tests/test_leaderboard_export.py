from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.export_leaderboard_package import load_pass_receipt


def _receipt(**overrides):
    payload = {
        "schemaVersion": "moneysweep.leaderboard-certification/v1",
        "state": "PASS",
        "certificationIssued": True,
        "zeroMaterialUnresolvedResidue": True,
        "promotionAuthorized": False,
    }
    payload.update(overrides)
    return payload


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.mark.unit
def test_blocked_receipt_cannot_be_loaded_for_promotion(tmp_path: Path):
    path = _write(tmp_path / "receipt.json", _receipt(state="BLOCKED", certificationIssued=False))
    with pytest.raises(SystemExit, match="not PASS/issued"):
        load_pass_receipt(path)


@pytest.mark.unit
def test_zero_residue_attestation_is_required(tmp_path: Path):
    path = _write(tmp_path / "receipt.json", _receipt(zeroMaterialUnresolvedResidue=False))
    with pytest.raises(SystemExit, match="zero material unresolved residue"):
        load_pass_receipt(path)


@pytest.mark.unit
def test_package_emission_requires_promotion_to_remain_closed(tmp_path: Path):
    path = _write(tmp_path / "receipt.json", _receipt(promotionAuthorized=True))
    with pytest.raises(SystemExit, match="promotion-closed"):
        load_pass_receipt(path)


@pytest.mark.unit
def test_valid_pass_receipt_is_accepted(tmp_path: Path):
    receipt = _receipt()
    path = _write(tmp_path / "receipt.json", receipt)
    assert load_pass_receipt(path) == receipt


@pytest.mark.unit
def test_asg_export_schema_is_strictly_bounded():
    root = Path(__file__).resolve().parents[1]
    schema = json.loads(
        (root / "schemas/leaderboard_export_package_asg_emergency_v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    props = schema["properties"]
    assert props["scopeId"]["const"] == "moneysweep.leaderboard.asg-emergency-source-native-v1"
    category = props["categories"]["items"]["properties"]
    assert category["categoryId"]["const"] == "asg_emergency_purchase_source_native"
    assert category["metricType"]["const"] == "ASG_EMERGENCY_PURCHASE_COST"
    accounting = category["accounting"]["properties"]
    assert accounting["inputRecords"]["const"] == 1431
    assert accounting["outOfScopeRecords"]["const"] == 1410
    assert accounting["retainedRecords"]["const"] == 21
    source = category["sourceVersion"]["properties"]
    assert source["type"]["const"] == "LIVE_PORTAL_MATERIALIZATION"
    assert source["ordering"]["const"] == "-numerocontrol"
    row = category["rows"]["items"]["properties"]
    assert row["entityResolutionState"]["const"] == "SOURCE_NATIVE_ASG_LICITADOR_ID"
    assert row["entityId"]["pattern"] == "^asg_licitador_id:[0-9]+$"
