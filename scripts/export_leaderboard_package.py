#!/usr/bin/env python3
"""Export certified MoneySweep leaderboard snapshots for TheHub.

The exporter never recomputes rankings. It packages separately certified,
hash-verified snapshots and binds them to the exact PASS producer receipt,
release manifest, bounded certification scope, and certification runtime.
TheHub separately trusts the exact package SHA-256, which binds all of these
fields without creating a release-receipt self-reference.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from scripts.leaderboard_release_provenance import (
    certification_runtime_manifest,
    certification_runtime_sha256,
    validate_certification_runtime,
)
from server.backend.leaderboard_history import verify_snapshot

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECEIPT = ROOT / "data" / "manifests" / "leaderboards" / "MONEYSWEEP_LEADERBOARD_CERTIFICATION.json"
DEFAULT_RELEASE = ROOT / "data" / "manifests" / "leaderboards" / "leaderboard_release_contract_v1.json"
DEFAULT_SCOPE = ROOT / "data" / "manifests" / "leaderboards" / "leaderboard_certification_scope_v1.json"
CERTIFIED_SNAPSHOT_DIR = ROOT / "data" / "manifests" / "leaderboards" / "certified_snapshots"
DEFAULT_OUT = ROOT / "data" / "exports" / "leaderboards" / "leaderboard_package.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"BLOCKED: required manifest not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"BLOCKED: invalid JSON manifest: {path}") from exc


def load_pass_receipt(path: Path) -> dict:
    receipt = _load_json(path)
    if receipt.get("schemaVersion") != "moneysweep.leaderboard-certification/v1":
        raise SystemExit("BLOCKED: unsupported leaderboard certification receipt schema")
    if receipt.get("state") != "PASS" or receipt.get("certificationIssued") is not True:
        raise SystemExit("BLOCKED: leaderboard certification receipt is not PASS/issued")
    if receipt.get("zeroMaterialUnresolvedResidue") is not True:
        raise SystemExit("BLOCKED: certification receipt does not attest zero material unresolved residue")
    if receipt.get("promotionAuthorized") is not True:
        raise SystemExit("BLOCKED: certification receipt does not authorize federation promotion")
    return receipt


def _scope_categories(scope: dict) -> set[str]:
    return {str(item.get("categoryId")) for item in scope.get("includedCategories") or [] if item.get("categoryId")}


def latest_certified_snapshot(category: str) -> dict:
    if not CERTIFIED_SNAPSHOT_DIR.exists():
        raise SystemExit(f"BLOCKED: certified snapshot directory not found: {CERTIFIED_SNAPSHOT_DIR}")
    candidates = []
    for path in sorted(CERTIFIED_SNAPSHOT_DIR.glob("*.json")):
        try:
            snapshot = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if snapshot.get("categoryId") != category:
            continue
        errors = verify_snapshot(snapshot)
        if errors:
            continue
        certification = snapshot.get("certification") or {}
        if snapshot.get("certificationState") != "PASS" or certification.get("state") != "PASS":
            continue
        if certification.get("zeroMaterialUnresolvedResidue") is not True:
            continue
        candidates.append(snapshot)
    if not candidates:
        raise SystemExit(f"BLOCKED: no certified PASS snapshot for category {category}")
    candidates.sort(key=lambda row: (str(row.get("capturedAt") or ""), str(row.get("snapshotId") or "")))
    return candidates[-1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--producer-commit", required=True)
    parser.add_argument("--category", action="append", dest="categories", required=True)
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--release-manifest", type=Path, default=DEFAULT_RELEASE)
    parser.add_argument("--scope", type=Path, default=DEFAULT_SCOPE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    producer_commit = args.producer_commit.lower()
    if len(producer_commit) != 40 or any(ch not in "0123456789abcdef" for ch in producer_commit):
        raise SystemExit("producer commit must be a lowercase 40-character git SHA")

    load_pass_receipt(args.receipt)
    release = _load_json(args.release_manifest)
    scope = _load_json(args.scope)
    if release.get("certification_state") != "PASS" or release.get("promotion_authorized") is not True:
        raise SystemExit("BLOCKED: release manifest is not PASS/promotion-authorized")
    if scope.get("schemaVersion") != "moneysweep.leaderboard-certification-scope/v1":
        raise SystemExit("BLOCKED: unsupported certification scope schema")
    scope_id = str(scope.get("scopeId") or "")
    if not scope_id:
        raise SystemExit("BLOCKED: certification scope has no scopeId")
    included = _scope_categories(scope)

    cert_runtime = certification_runtime_manifest()
    cert_runtime_errors = validate_certification_runtime(cert_runtime)
    if cert_runtime_errors:
        raise SystemExit(f"BLOCKED: certification runtime is not frozen: {cert_runtime_errors}")
    cert_runtime_hash = certification_runtime_sha256(cert_runtime)

    requested = list(dict.fromkeys(args.categories))
    outside = sorted(set(requested) - included)
    if outside:
        raise SystemExit(f"BLOCKED: requested categories outside certified scope: {outside}")

    category_payloads = []
    for category in requested:
        snapshot = latest_certified_snapshot(category)
        certification = snapshot.get("certification") or {}
        if certification.get("scopeId") != scope_id:
            raise SystemExit(f"BLOCKED: certified snapshot scope mismatch: {category}")
        runtime_manifest = snapshot.get("runtimeManifest") or {}
        if runtime_manifest.get("state") != "FROZEN":
            raise SystemExit(f"BLOCKED: snapshot runtime manifestation is not frozen: {category}")
        if runtime_manifest.get("producerCommit") != producer_commit:
            raise SystemExit(f"BLOCKED: snapshot producer commit does not match export commit: {category}")
        category_payloads.append(
            {
                "categoryId": snapshot["categoryId"],
                "metricType": snapshot["metricType"],
                "snapshotId": snapshot["snapshotId"],
                "snapshotSha256": snapshot["snapshotSha256"],
                "capturedAt": snapshot["capturedAt"],
                "candidateCount": snapshot["candidateCount"],
                "accounting": snapshot["accounting"],
                "sourceVersion": snapshot.get("sourceVersion") or {},
                "sourceManifestations": snapshot["sourceManifestations"],
                "runtimeManifest": runtime_manifest,
                "snapshotCertification": certification,
                "rows": snapshot["rows"],
            }
        )

    package = {
        "schemaVersion": "moneysweep.leaderboard-export-package/v1",
        "producer": "moneysweep-pr",
        "producerCommit": producer_commit,
        "rankingContractVersion": "moneysweep.leaderboard/v1.1",
        "ontologyContractVersion": "moneysweep.financial-category-ontology/v1.1",
        "scopeId": scope_id,
        "generatedAt": datetime.now(tz=UTC).replace(microsecond=0).isoformat(),
        "certification": {
            "state": "PASS",
            "receiptSha256": sha256(args.receipt),
            "releaseManifestSha256": sha256(args.release_manifest),
            "scopeSha256": sha256(args.scope),
            "certificationRuntimeSha256": cert_runtime_hash,
        },
        "certificationRuntimeManifest": cert_runtime,
        "categories": category_payloads,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(package, indent=2, sort_keys=True) + "\n"
    args.output.write_text(rendered, encoding="utf-8")
    print(
        json.dumps(
            {
                "state": "PASS",
                "output": str(args.output),
                "sha256": sha256(args.output),
                "scopeId": scope_id,
                "certificationRuntimeSha256": cert_runtime_hash,
                "categories": len(category_payloads),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
