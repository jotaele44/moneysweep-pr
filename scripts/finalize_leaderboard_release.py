#!/usr/bin/env python3
"""Close the bounded MoneySweep leaderboard release without relying on Actions.

The finalizer performs the non-CI release chain in one fail-closed transaction:
1. replay the pinned debt source history under one frozen ranking runtime;
2. verify the expected dataset-delta movement receipt;
3. certify the current debt snapshot against the bounded production scope;
4. issue producer PASS while federation promotion remains closed;
5. when a TheHub checkout is supplied, temporarily authorize promotion,
   generate the exact package, run TheHub's consumer/cross-repo regressions,
   mount the exact package at TheHub's default product path, verify that mount,
   and roll promotion back if any replay step fails.

GitHub Actions execution can be waived by scope policy, but this script never
represents that waiver as a passing test result. Frozen snapshots and comparison
receipts are immutable: a rerun may reuse byte-identical artifacts but cannot
silently replace them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.certify_leaderboard_snapshot import certify
from scripts.materialize_leaderboard_git_snapshot import _replay_ranking, _resolve_commit
from scripts.materialize_leaderboard_snapshot import _runtime_manifest
from server.backend.leaderboard_history import (
    SNAPSHOT_DIR,
    compare,
    make_snapshot,
    snapshot_sha256,
    verify_snapshot,
)

ROOT = Path(__file__).resolve().parents[1]
LEADERBOARD_DIR = ROOT / "data" / "manifests" / "leaderboards"
HISTORY_REFS = LEADERBOARD_DIR / "debt_history_source_refs_v1.json"
SCOPE_PATH = LEADERBOARD_DIR / "leaderboard_certification_scope_v1.json"
RELEASE_PATH = LEADERBOARD_DIR / "leaderboard_release_contract_v1.json"
RECEIPT_PATH = LEADERBOARD_DIR / "MONEYSWEEP_LEADERBOARD_CERTIFICATION.json"
HISTORY_RECEIPT_PATH = LEADERBOARD_DIR / "debt_history_comparison_v1.json"
CERTIFIED_DIR = LEADERBOARD_DIR / "certified_snapshots"
PACKAGE_PATH = ROOT / "data" / "exports" / "leaderboards" / "leaderboard_package.json"


def _load(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"release blocked: missing {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"release blocked: invalid JSON {path}") from exc


def _render(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_atomic(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_bytes(raw)
    os.replace(temp, path)


def _write_immutable(path: Path, raw: bytes) -> None:
    if path.exists():
        if path.read_bytes() == raw:
            return
        raise SystemExit(f"release blocked: refusing to overwrite immutable artifact {path}")
    _write_atomic(path, raw)


def _history_snapshot(
    *,
    source_ref: dict[str, Any],
    runtime: dict[str, Any],
    currency: str = "USD",
) -> dict[str, Any]:
    commit = _resolve_commit(str(source_ref["commit"]))
    if commit != source_ref["commit"]:
        raise SystemExit(f"release blocked: source ref did not resolve exactly: {source_ref['commit']}")
    ranking, _ = _replay_ranking(
        source_commit=commit,
        category="debt_issuance",
        start_year=None,
        end_year=None,
        municipality=None,
        entity_type=None,
        currency=currency,
    )
    accounting = ranking.get("accounting") or {}
    if accounting.get("arithmeticClosed") is not True:
        raise SystemExit(f"release blocked: ranking accounting did not close for {commit}")
    snapshot = make_snapshot(
        ranking,
        captured_at=str(source_ref["committedAt"]),
        snapshot_id=f"debt_issuance:git:{commit[:12]}",
        runtime_manifest=runtime,
    )
    snapshot["snapshotMode"] = "HISTORICAL_GIT_SOURCE_REPLAY"
    snapshot["sourceVersion"] = {
        "type": "GIT_COMMIT",
        "commit": commit,
        "committedAt": source_ref["committedAt"],
        "economicActivityInference": False,
    }
    snapshot["snapshotSha256"] = snapshot_sha256(snapshot)
    errors = verify_snapshot(snapshot)
    if errors:
        raise SystemExit(f"release blocked: invalid replay snapshot {commit}: {errors}")
    return snapshot


def _verify_expected_delta(result: dict[str, Any], expected: dict[str, Any]) -> None:
    if result.get("movementState") != "COMPARABLE_SNAPSHOT_DELTA":
        raise SystemExit(f"release blocked: historical comparison state={result.get('movementState')}")
    if result.get("sourceManifestationChanged") is not True:
        raise SystemExit("release blocked: expected debt source manifestation change was not observed")
    if result.get("runtimeManifestationChanged") is not False:
        raise SystemExit("release blocked: historical replays did not use one frozen runtime")
    if result.get("economicChangeInferenceAllowed") is not False:
        raise SystemExit("release blocked: source-changing history cannot authorize economic-change inference")
    counts = result.get("movementCounts") or {}
    for state in ("NEW", "EXITED", "UP", "DOWN", "UNCHANGED"):
        if counts.get(state) != expected.get(state):
            raise SystemExit(
                f"release blocked: historical movement mismatch {state}: expected={expected.get(state)} observed={counts.get(state)}"
            )
    existing_value_changes = sum(
        1
        for row in result.get("rows") or []
        if row.get("movementState") not in {"NEW", "EXITED"} and float(row.get("valueDelta") or 0) != 0
    )
    if existing_value_changes != expected.get("existingEntityValueChanges"):
        raise SystemExit("release blocked: existing-entity value delta count does not match frozen expectation")


def _history_receipt(prior: dict[str, Any], current: dict[str, Any], movement: dict[str, Any]) -> dict[str, Any]:
    receipt = {
        "schemaVersion": "moneysweep.leaderboard-history-comparison/v1",
        "categoryId": "debt_issuance",
        "metricType": "DEBT_ISSUED_PAR",
        "priorSnapshotId": prior["snapshotId"],
        "priorSnapshotSha256": prior["snapshotSha256"],
        "currentSnapshotId": current["snapshotId"],
        "currentSnapshotSha256": current["snapshotSha256"],
        "movementState": movement["movementState"],
        "movementCounts": movement["movementCounts"],
        "sourceManifestationChanged": movement["sourceManifestationChanged"],
        "runtimeManifestationChanged": movement["runtimeManifestationChanged"],
        "economicChangeInferenceAllowed": movement["economicChangeInferenceAllowed"],
        "classification": "DATASET_CHANGE_CONTROL_DELTA",
    }
    receipt["receiptSha256"] = _sha_bytes(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    return receipt


def _producer_documents(
    *,
    release_template: dict[str, Any],
    receipt_template: dict[str, Any],
    runtime_commit: str,
    certified_snapshot: dict[str, Any],
    history_receipt: dict[str, Any],
    scope_hash: str,
    promote: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    release = dict(release_template)
    release["certification_state"] = "PASS"
    release["certification_issued"] = True
    release["promotion_authorized"] = promote
    release["runtime_producer_commit"] = runtime_commit
    release["certified_snapshot_sha256"] = certified_snapshot["snapshotSha256"]
    release["history_comparison_sha256"] = history_receipt["receiptSha256"]
    release["scope_sha256"] = scope_hash
    release["blockers"] = [] if promote else [
        {
            "id": "THEHUB_EXACT_REPLAY",
            "state": "OPEN",
            "reason": "Producer certification passed; federation promotion awaits exact TheHub package replay."
        }
    ]

    receipt = dict(receipt_template)
    receipt["state"] = "PASS"
    receipt["certificationIssued"] = True
    receipt["zeroMaterialUnresolvedResidue"] = True
    receipt["runtimeProducerCommit"] = runtime_commit
    receipt["certifiedSnapshotSha256"] = certified_snapshot["snapshotSha256"]
    receipt["historyComparisonSha256"] = history_receipt["receiptSha256"]
    receipt["scopeSha256"] = scope_hash
    receipt["blockingResidue"] = [] if promote else [
        {
            "id": "THEHUB_EXACT_REPLAY",
            "state": "OPEN",
            "reason": "Producer certification passed; federation promotion awaits exact TheHub package replay."
        }
    ]
    receipt["promotionAuthorized"] = promote
    receipt["certificationPhraseAuthorized"] = promote
    receipt["note"] = (
        "Bounded leaderboard scope certified and exact TheHub replay passed."
        if promote
        else "Bounded producer scope certified; federation promotion remains closed pending exact TheHub replay."
    )
    return release, receipt


def _run_export(runtime_commit: str) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/export_leaderboard_package.py",
            "--producer-commit",
            runtime_commit,
            "--category",
            "debt_issuance",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "leaderboard export failed")


def _run_thehub_replay(thehub_root: Path) -> None:
    env = os.environ.copy()
    env["PRII_MONEYSWEEP_REPO"] = str(ROOT)
    env["PRII_REQUIRE_MONEYSWEEP_LEADERBOARD_CONTRACT"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_moneysweep_leaderboard_consumer.py",
            "tests/test_moneysweep_leaderboard_crossrepo.py",
            "-q",
        ],
        cwd=thehub_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=180,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stdout + "\n" + result.stderr)


def _run_thehub_mounted_check(thehub_root: Path) -> None:
    env = os.environ.copy()
    env["PRII_MONEYSWEEP_LEADERBOARD_RECEIPT_SHA256"] = _sha_file(RECEIPT_PATH)
    env["PRII_MONEYSWEEP_LEADERBOARD_RELEASE_SHA256"] = _sha_file(RELEASE_PATH)
    env["PRII_MONEYSWEEP_LEADERBOARD_SCOPE_SHA256"] = _sha_file(SCOPE_PATH)
    env["PRII_MONEYSWEEP_LEADERBOARD_PACKAGE_SHA256"] = _sha_file(PACKAGE_PATH)
    code = (
        "from server.backend import moneysweep_leaderboards as c; "
        "p=c._load_package(); "
        "assert p['scopeId']==c.EXPECTED_SCOPE; "
        "assert len(p['categories'])==1; "
        "assert p['categories'][0]['categoryId']==c.EXPECTED_CATEGORY; "
        "assert p['consumerPackageSha256']"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=thehub_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stdout + "\n" + result.stderr)


def _reuse_or_certify(current: dict[str, Any], scope: dict[str, Any]) -> tuple[dict[str, Any], Path]:
    CERTIFIED_DIR.mkdir(parents=True, exist_ok=True)
    path = CERTIFIED_DIR / f"{current['snapshotId'].replace(':', '_')}.json"
    if path.exists():
        certified = _load(path)
        certification = certified.get("certification") or {}
        if certification.get("sourceSnapshotSha256") != current.get("snapshotSha256"):
            raise SystemExit(
                "release blocked: immutable certified snapshot belongs to a different ranking runtime/source snapshot"
            )
        if certification.get("scopeId") != scope.get("scopeId"):
            raise SystemExit("release blocked: immutable certified snapshot scope mismatch")
        if verify_snapshot(certified):
            raise SystemExit("release blocked: existing certified snapshot is invalid")
        return certified, path
    certified_at = datetime.now(tz=UTC).replace(microsecond=0).isoformat()
    try:
        certified = certify(current, scope, certified_at=certified_at)
    except ValueError as exc:
        raise SystemExit(f"release blocked: current debt snapshot certification failed: {exc}") from exc
    return certified, path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--thehub-root", type=Path)
    args = parser.parse_args()

    history_refs = _load(HISTORY_REFS)
    scope = _load(SCOPE_PATH)
    release_template = _load(RELEASE_PATH)
    receipt_template = _load(RECEIPT_PATH)
    if scope.get("scopeId") != "moneysweep.leaderboard.production-v1":
        raise SystemExit("release blocked: unexpected production scope")
    if [item.get("categoryId") for item in scope.get("includedCategories") or []] != ["debt_issuance"]:
        raise SystemExit("release blocked: production scope category drift")
    if (scope.get("ciExecutionPolicy") or {}).get("state") != "WAIVED_BY_USER":
        raise SystemExit("release blocked: this finalizer expects the explicit GitHub Actions waiver")

    runtime = _runtime_manifest()
    runtime_commit = str(runtime.get("producerCommit") or "")
    if len(runtime_commit) != 40 or any(ch not in "0123456789abcdef" for ch in runtime_commit):
        raise SystemExit("release blocked: exact ranking runtime commit unresolved")
    if any(item.get("state") == "MISSING" for item in runtime.get("files") or []):
        raise SystemExit("release blocked: ranking runtime manifestation incomplete")

    refs = history_refs.get("sourceRefs") or []
    if len(refs) != 2 or [item.get("role") for item in refs] != ["baseline", "current"]:
        raise SystemExit("release blocked: expected exactly baseline/current debt source refs")
    prior = _history_snapshot(source_ref=refs[0], runtime=runtime)
    current = _history_snapshot(source_ref=refs[1], runtime=runtime)
    movement = compare(prior, current, limit=25)
    _verify_expected_delta(movement, history_refs.get("expectedDelta") or {})
    history_receipt = _history_receipt(prior, current, movement)
    certified, certified_path = _reuse_or_certify(current, scope)

    scope_hash = _sha_file(SCOPE_PATH)
    producer_release, producer_receipt = _producer_documents(
        release_template=release_template,
        receipt_template=receipt_template,
        runtime_commit=runtime_commit,
        certified_snapshot=certified,
        history_receipt=history_receipt,
        scope_hash=scope_hash,
        promote=False,
    )

    # Immutable evidence artifacts are written before mutable release decisions.
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    for snapshot in (prior, current):
        _write_immutable(
            SNAPSHOT_DIR / f"{snapshot['snapshotId'].replace(':', '_')}.json",
            _render(snapshot),
        )
    _write_immutable(HISTORY_RECEIPT_PATH, _render(history_receipt))
    _write_immutable(certified_path, _render(certified))
    _write_atomic(RELEASE_PATH, _render(producer_release))
    _write_atomic(RECEIPT_PATH, _render(producer_receipt))

    if args.thehub_root is None:
        print(
            json.dumps(
                {
                    "state": "PRODUCER_PASS_AWAITING_THEHUB_REPLAY",
                    "runtimeProducerCommit": runtime_commit,
                    "certifiedSnapshotSha256": certified["snapshotSha256"],
                    "historyComparisonSha256": history_receipt["receiptSha256"],
                    "scopeSha256": scope_hash,
                    "promotionAuthorized": False,
                },
                indent=2,
            )
        )
        return 0

    thehub_root = args.thehub_root.expanduser().resolve()
    if not (thehub_root / "tests" / "test_moneysweep_leaderboard_crossrepo.py").exists():
        raise SystemExit(f"release blocked: TheHub consumer checkout not found at {thehub_root}")

    promoted_release, promoted_receipt = _producer_documents(
        release_template=producer_release,
        receipt_template=producer_receipt,
        runtime_commit=runtime_commit,
        certified_snapshot=certified,
        history_receipt=history_receipt,
        scope_hash=scope_hash,
        promote=True,
    )
    previous_release = RELEASE_PATH.read_bytes()
    previous_receipt = RECEIPT_PATH.read_bytes()
    previous_package = PACKAGE_PATH.read_bytes() if PACKAGE_PATH.exists() else None
    target = thehub_root / "data" / "aggregate" / "moneysweep" / "leaderboard_package.json"
    previous_target = target.read_bytes() if target.exists() else None
    try:
        _write_atomic(RELEASE_PATH, _render(promoted_release))
        _write_atomic(RECEIPT_PATH, _render(promoted_receipt))
        _run_export(runtime_commit)
        _run_thehub_replay(thehub_root)
        _write_atomic(target, PACKAGE_PATH.read_bytes())
        _run_thehub_mounted_check(thehub_root)
    except Exception as exc:
        _write_atomic(RELEASE_PATH, previous_release)
        _write_atomic(RECEIPT_PATH, previous_receipt)
        if previous_package is None:
            if PACKAGE_PATH.exists():
                PACKAGE_PATH.unlink()
        else:
            _write_atomic(PACKAGE_PATH, previous_package)
        if previous_target is None:
            if target.exists():
                target.unlink()
        else:
            _write_atomic(target, previous_target)
        raise SystemExit(f"promotion rolled back: {exc}") from exc

    print(
        json.dumps(
            {
                "state": "PASS",
                "runtimeProducerCommit": runtime_commit,
                "certifiedSnapshotSha256": certified["snapshotSha256"],
                "historyComparisonSha256": history_receipt["receiptSha256"],
                "receiptSha256": _sha_file(RECEIPT_PATH),
                "releaseManifestSha256": _sha_file(RELEASE_PATH),
                "scopeSha256": scope_hash,
                "packageSha256": _sha_file(PACKAGE_PATH),
                "thehubPackage": str(target),
                "promotionAuthorized": True,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
