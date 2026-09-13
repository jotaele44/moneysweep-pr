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
        "promotionAuthorized": True,
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
def test_explicit_promotion_authorization_is_required(tmp_path: Path):
    path = _write(tmp_path / "receipt.json", _receipt(promotionAuthorized=False))
    with pytest.raises(SystemExit, match="authorize federation promotion"):
        load_pass_receipt(path)


@pytest.mark.unit
def test_valid_pass_receipt_is_accepted(tmp_path: Path):
    receipt = _receipt()
    path = _write(tmp_path / "receipt.json", receipt)
    assert load_pass_receipt(path) == receipt
