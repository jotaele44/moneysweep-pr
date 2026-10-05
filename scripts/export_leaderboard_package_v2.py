#!/usr/bin/env python3
"""Export MoneySweep production-v2 leaderboard package without recomputation.

V2 intentionally permits independently frozen category runtimes. The package
assembler commit identifies this exporter manifestation; each certified
snapshot retains its own runtimeManifest.producerCommit.
"""
from __future__ import annotations
import argparse, hashlib, json
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEADER = ROOT / "data" / "manifests" / "leaderboards"
DEFAULT_RECEIPT = LEADER / "MONEYSWEEP_LEADERBOARD_CERTIFICATION_V2.json"
DEFAULT_RELEASE = LEADER / "leaderboard_release_contract_v2.json"
DEFAULT_SCOPE = LEADER / "leaderboard_certification_scope_v2.json"
DEFAULT_SCHEMA = ROOT / "schemas" / "leaderboard_export_package_v2.schema.json"
DEFAULT_OUT = ROOT / "data" / "exports" / "leaderboards" / "leaderboard_package_v2.json"
SNAPSHOTS = {
    "debt_issuance": LEADER / "certified_snapshots" / "debt_issuance_git_1be586b5ae13_v2.json",
    "asg_emergency_purchase_source_native": LEADER / "certified_snapshots" / "asg_emergency_purchase_source_native_20261005T134917Z.json",
}
RUNTIME_FILES = [
    ROOT / "scripts" / "export_leaderboard_package_v2.py",
    DEFAULT_SCHEMA,
    DEFAULT_SCOPE,
]

def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"BLOCKED: missing {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"BLOCKED: invalid JSON {path}") from exc

def is_sha(value: object, length: int) -> bool:
    text = str(value or "")
    return len(text) == length and all(ch in "0123456789abcdef" for ch in text.lower())

def manifest(paths: list[Path]) -> dict:
    files=[]
    for path in paths:
        if not path.exists():
            raise SystemExit(f"BLOCKED: certification-runtime file missing: {path}")
        files.append({"path":str(path.relative_to(ROOT)),"bytes":path.stat().st_size,"sha256":sha256(path)})
    return {"schemaVersion":"moneysweep.leaderboard-certification-runtime/v2","state":"FROZEN","files":files}

def canonical_sha(value: object) -> str:
    rendered=json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False)
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()

def validate_snapshot(category: str, snapshot: dict, scope_id: str) -> None:
    cert=snapshot.get("certification") or {}
    if snapshot.get("categoryId") != category:
        raise SystemExit(f"BLOCKED: category mismatch: {category}")
    if snapshot.get("certificationState") != "PASS" or cert.get("state") != "PASS":
        raise SystemExit(f"BLOCKED: snapshot is not PASS: {category}")
    if cert.get("scopeId") != scope_id:
        raise SystemExit(f"BLOCKED: snapshot scope mismatch: {category}")
    if cert.get("zeroMaterialUnresolvedResidue") is not True:
        raise SystemExit(f"BLOCKED: unresolved residue: {category}")
    copy=dict(snapshot); expected=copy.pop("snapshotSha256",None)
    if expected != canonical_sha(copy):
        raise SystemExit(f"BLOCKED: snapshot hash mismatch: {category}")
    acct=snapshot.get("accounting") or {}
    if acct.get("arithmeticClosed") is not True or acct.get("unresolvedRecords") != 0 or acct.get("excludedRecords") != 0:
        raise SystemExit(f"BLOCKED: accounting not closed: {category}")
    runtime=snapshot.get("runtimeManifest") or {}
    if runtime.get("state") != "FROZEN" or not is_sha(runtime.get("producerCommit"),40):
        raise SystemExit(f"BLOCKED: invalid runtime: {category}")

def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("--assembler-commit",required=True)
    p.add_argument("--receipt",type=Path,default=DEFAULT_RECEIPT)
    p.add_argument("--release-manifest",type=Path,default=DEFAULT_RELEASE)
    p.add_argument("--scope",type=Path,default=DEFAULT_SCOPE)
    p.add_argument("--output",type=Path,default=DEFAULT_OUT)
    args=p.parse_args()
    assembler=args.assembler_commit.lower()
    if not is_sha(assembler,40):
        raise SystemExit("BLOCKED: assembler commit must be a 40-character SHA")

    receipt=load(args.receipt); release=load(args.release_manifest); scope=load(args.scope)
    if receipt.get("schemaVersion") != "moneysweep.leaderboard-certification/v2" or receipt.get("state") != "PASS":
        raise SystemExit("BLOCKED: v2 producer receipt not PASS")
    if receipt.get("certificationIssued") is not True or receipt.get("zeroMaterialUnresolvedResidue") is not True:
        raise SystemExit("BLOCKED: v2 producer receipt not issued/closed")
    if receipt.get("promotionAuthorized") is not False:
        raise SystemExit("BLOCKED: producer receipt must remain promotion-closed")
    if release.get("schemaVersion") != "moneysweep.leaderboard-release/v2" or release.get("certification_state") != "PASS":
        raise SystemExit("BLOCKED: v2 release not PASS")
    if release.get("promotion_authorized") is not False:
        raise SystemExit("BLOCKED: v2 release must remain promotion-closed")
    if scope.get("scopeId") != "moneysweep.leaderboard.production-v2":
        raise SystemExit("BLOCKED: wrong v2 scope")

    categories=[]
    for item in scope.get("includedCategories") or []:
        category=str(item.get("categoryId") or "")
        if category not in SNAPSHOTS:
            raise SystemExit(f"BLOCKED: no frozen v2 snapshot mapping for {category}")
        snapshot=load(SNAPSHOTS[category])
        validate_snapshot(category,snapshot,scope["scopeId"])
        categories.append({
            "categoryId":snapshot["categoryId"],"metricType":snapshot["metricType"],
            "snapshotId":snapshot["snapshotId"],"snapshotSha256":snapshot["snapshotSha256"],
            "capturedAt":snapshot["capturedAt"],"candidateCount":snapshot["candidateCount"],
            "accounting":snapshot["accounting"],"sourceVersion":snapshot.get("sourceVersion") or {},
            "sourceManifestations":snapshot["sourceManifestations"],"runtimeManifest":snapshot["runtimeManifest"],
            "snapshotCertification":snapshot["certification"],"rows":snapshot["rows"],
        })
    if {x["categoryId"] for x in categories} != set(SNAPSHOTS):
        raise SystemExit("BLOCKED: v2 category denominator mismatch")

    cert_runtime=manifest(RUNTIME_FILES)
    package={
        "schemaVersion":"moneysweep.leaderboard-export-package/v2",
        "producer":"moneysweep-pr",
        "packageAssemblerCommit":assembler,
        "rankingContractVersion":"moneysweep.leaderboard/v1.1",
        "ontologyContractVersion":"moneysweep.financial-category-ontology/v1.1",
        "scopeId":scope["scopeId"],
        "generatedAt":datetime.now(tz=UTC).replace(microsecond=0).isoformat(),
        "certification":{
            "state":"PASS","receiptSha256":sha256(args.receipt),
            "releaseManifestSha256":sha256(args.release_manifest),
            "scopeSha256":sha256(args.scope),
            "certificationRuntimeSha256":canonical_sha(cert_runtime),
        },
        "certificationRuntimeManifest":cert_runtime,
        "categories":categories,
    }
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(package,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({"state":"PASS","output":str(args.output),"sha256":sha256(args.output),"categories":len(categories)},indent=2))
    return 0
if __name__=="__main__":
    raise SystemExit(main())
