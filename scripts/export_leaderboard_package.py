#!/usr/bin/env python3
"""Export certified MoneySweep leaderboard snapshots for TheHub.

This exporter is intentionally unusable before producer certification. It never
recomputes financial rankings; it packages already-frozen verified snapshots and
binds them to a PASS certification receipt and release-manifest hash.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from server.backend.leaderboard_history import list_snapshots, verify_snapshot

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECEIPT = ROOT / "data" / "manifests" / "leaderboards" / "MONEYSWEEP_LEADERBOARD_CERTIFICATION.json"
DEFAULT_RELEASE = ROOT / "data" / "manifests" / "leaderboards" / "leaderboard_release_contract_v1.json"
DEFAULT_OUT = ROOT / "data" / "exports" / "leaderboards" / "leaderboard_package.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_pass_receipt(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"BLOCKED: certification receipt not found: {path}")
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if receipt.get("schemaVersion") != "moneysweep.leaderboard-certification/v1":
        raise SystemExit("BLOCKED: unsupported leaderboard certification receipt schema")
    if receipt.get("state") != "PASS" or receipt.get("certificationIssued") is not True:
        raise SystemExit("BLOCKED: leaderboard certification receipt is not PASS/issued")
    if receipt.get("zeroMaterialUnresolvedResidue") is not True:
        raise SystemExit("BLOCKED: certification receipt does not attest zero material unresolved residue")
    return receipt


def latest_snapshot(category: str) -> dict:
    snapshots = list_snapshots(category)
    if not snapshots:
        raise SystemExit(f"BLOCKED: no verified frozen snapshot for category {category}")
    snapshot = snapshots[-1]
    errors = verify_snapshot(snapshot)
    if errors:
        raise SystemExit(f"BLOCKED: invalid snapshot {snapshot.get('snapshotId')}: {errors}")
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--producer-commit", required=True)
    parser.add_argument("--category", action="append", dest="categories", required=True)
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--release-manifest", type=Path, default=DEFAULT_RELEASE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    if len(args.producer_commit) != 40 or any(ch not in "0123456789abcdef" for ch in args.producer_commit):
        raise SystemExit("producer commit must be a lowercase 40-character git SHA")
    receipt = load_pass_receipt(args.receipt)
    if not args.release_manifest.exists():
        raise SystemExit(f"BLOCKED: release manifest missing: {args.release_manifest}")

    category_payloads = []
    for category in dict.fromkeys(args.categories):
        snapshot = latest_snapshot(category)
        if snapshot.get("certificationState") not in {"PASS", "PROVISIONAL"}:
            raise SystemExit(f"BLOCKED: snapshot state not promotable: {category} {snapshot.get('certificationState')}")
        category_payloads.append({
            "categoryId": snapshot["categoryId"],
            "metricType": snapshot["metricType"],
            "snapshotId": snapshot["snapshotId"],
            "snapshotSha256": snapshot["snapshotSha256"],
            "rows": snapshot["rows"],
        })

    package = {
        "schemaVersion": "moneysweep.leaderboard-export-package/v1",
        "producer": "moneysweep-pr",
        "producerCommit": args.producer_commit,
        "rankingContractVersion": "moneysweep.leaderboard/v1.1",
        "ontologyContractVersion": "moneysweep.financial-category-ontology/v1.1",
        "generatedAt": datetime.now(tz=UTC).replace(microsecond=0).isoformat(),
        "certification": {
            "state": "PASS",
            "receiptSha256": sha256(args.receipt),
            "releaseManifestSha256": sha256(args.release_manifest),
        },
        "categories": category_payloads,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(package, indent=2, sort_keys=True) + "\n"
    args.output.write_text(rendered, encoding="utf-8")
    print(json.dumps({"state": "PASS", "output": str(args.output), "sha256": sha256(args.output), "categories": len(category_payloads)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
