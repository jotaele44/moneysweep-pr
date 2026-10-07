from __future__ import annotations

import json
from pathlib import Path

from tools.certify_production import _validate_activation_receipt


def _receipt() -> dict:
    return {
        "schema_version": "moneysweep.production_activation/v1",
        "scope_id": "a" * 64,
        "scope_sha": "b" * 40,
        "implementation_sha": "c" * 40,
        "certificate_sha256": "d" * 64,
        "authorized_by": "operator",
        "authorization_timestamp": "2026-09-28T00:00:00+00:00",
        "authorization_channel": "explicit_operator_authorization",
    }


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _validate(path: Path):
    return _validate_activation_receipt(
        path=path,
        scope_id="a" * 64,
        scope_sha="b" * 40,
        implementation_sha="c" * 40,
        certificate_sha256="d" * 64,
    )


def test_missing_activation_receipt_fails_closed(tmp_path: Path) -> None:
    valid, evidence, blockers = _validate(tmp_path / "missing.json")

    assert valid is False
    assert evidence["exists"] is False
    assert blockers == ["production_activation_receipt_missing"]


def test_matching_activation_receipt_is_valid(tmp_path: Path) -> None:
    path = tmp_path / "activation.json"
    _write(path, _receipt())

    valid, evidence, blockers = _validate(path)

    assert valid is True
    assert blockers == []
    assert evidence["receipt_sha256"] is not None
    assert evidence["certificate_sha256"] == "d" * 64


def test_stale_certificate_hash_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "activation.json"
    payload = _receipt()
    payload["certificate_sha256"] = "e" * 64
    _write(path, payload)

    valid, _, blockers = _validate(path)

    assert valid is False
    assert "production_activation_certificate_hash_mismatch" in blockers


def test_scope_and_implementation_mismatch_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "activation.json"
    payload = _receipt()
    payload["scope_id"] = "f" * 64
    payload["scope_sha"] = "1" * 40
    payload["implementation_sha"] = "2" * 40
    _write(path, payload)

    valid, _, blockers = _validate(path)

    assert valid is False
    assert "production_activation_scope_id_mismatch" in blockers
    assert "production_activation_scope_sha_mismatch" in blockers
    assert "production_activation_implementation_sha_mismatch" in blockers


def test_naive_timestamp_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "activation.json"
    payload = _receipt()
    payload["authorization_timestamp"] = "2026-09-28T00:00:00"
    _write(path, payload)

    valid, _, blockers = _validate(path)

    assert valid is False
    assert "production_activation_timestamp_timezone_missing" in blockers


def test_unexpected_keys_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "activation.json"
    payload = _receipt()
    payload["production_eligible"] = True
    _write(path, payload)

    valid, _, blockers = _validate(path)

    assert valid is False
    assert any(
        blocker.startswith("production_activation_receipt_unexpected_keys:")
        for blocker in blockers
    )
