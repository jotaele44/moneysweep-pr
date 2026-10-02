"""Remediate the known internal-reference-seed/T1 provenance contradiction.

This is intentionally narrow. It does not infer that every repository-local
source is non-authoritative. It only adjudicates the already identified
``data/reference/pr_public_money_entities.csv`` seed, preserving RAW source
strings while downgrading the derived evidence classification until an
independent authoritative binding exists.

Writes are restartable and atomic per file. Before mutation, exact input bytes
are copied into a timestamped SUPERSEDED snapshot with SHA256 and row counts.

Usage:
  python scripts/remediate_canonical_evidence_provenance.py --check
  python scripts/remediate_canonical_evidence_provenance.py --apply
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = Path("data/canonical_v1/evidence.csv")
ENTITIES = Path("data/canonical_v1/entities.csv")
TARGET_PATH = "data/reference/pr_public_money_entities.csv"
TARGET_SOURCE = "PR Public-Money Institutions (reference seed)"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return list(reader.fieldnames or []), list(reader)


def target_evidence(row: dict[str, str]) -> bool:
    return (row.get("source_path_or_url") or "").strip() == TARGET_PATH and (
        row.get("source_name") or ""
    ).strip() == TARGET_SOURCE


def plan(root: Path) -> dict:
    evidence_fields, evidence_rows = read_rows(root / EVIDENCE)
    entity_fields, entity_rows = read_rows(root / ENTITIES)
    affected_evidence = [r for r in evidence_rows if target_evidence(r)]
    affected_ids = {r["evidence_id"] for r in affected_evidence}
    affected_entities = [r for r in entity_rows if (r.get("evidence_id") or "") in affected_ids]
    residue = [
        r["evidence_id"]
        for r in affected_evidence
        if r.get("evidence_tier") == "T1" or r.get("review_status") == "accepted"
    ]
    return {
        "evidence_fields": evidence_fields,
        "entity_fields": entity_fields,
        "evidence_rows": evidence_rows,
        "entity_rows": entity_rows,
        "affected_evidence_count": len(affected_evidence),
        "affected_entity_count": len(affected_entities),
        "affected_evidence_ids": sorted(affected_ids),
        "unremediated_residue": residue,
    }


def atomic_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="raise")
            writer.writeheader()
            writer.writerows(rows)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            # Preserve the original write failure if the temp file is already gone.
            pass
        raise


def apply(root: Path) -> dict:
    before = plan(root)
    if not before["affected_evidence_count"]:
        raise RuntimeError("target seed evidence not found; refusing broad remediation")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot_dir = root / "data/manifests/database_certification/superseded" / timestamp
    snapshot_dir.mkdir(parents=True, exist_ok=False)

    before_meta = {}
    for rel in (EVIDENCE, ENTITIES):
        src = root / rel
        dst = snapshot_dir / rel.name
        shutil.copy2(src, dst)
        before_meta[rel.as_posix()] = {
            "sha256": sha256(src),
            "snapshot_path": dst.relative_to(root).as_posix(),
        }

    affected_ids = set(before["affected_evidence_ids"])
    for row in before["evidence_rows"]:
        if row.get("evidence_id") in affected_ids:
            # RAW source strings are preserved exactly. Only derived certification
            # fields change: T1 -> T3, accepted -> pending, confidence -> 0.6.
            row["evidence_tier"] = "T3"
            row["confidence"] = "0.6"
            row["review_status"] = "pending"
    for row in before["entity_rows"]:
        if (row.get("evidence_id") or "") in affected_ids:
            row["confidence"] = "0.6"
            row["review_status"] = "pending"

    atomic_csv(root / EVIDENCE, before["evidence_fields"], before["evidence_rows"])
    atomic_csv(root / ENTITIES, before["entity_fields"], before["entity_rows"])

    after = plan(root)
    if after["unremediated_residue"]:
        raise RuntimeError("post-write provenance residue remains")

    manifest = {
        "state": "SUPERSEDED_TO_REMEDIATED",
        "scope": TARGET_PATH,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "classification": "SOURCE_TAXONOMY_NOT_IDENTITY",
        "before": before_meta,
        "after": {
            EVIDENCE.as_posix(): {"sha256": sha256(root / EVIDENCE)},
            ENTITIES.as_posix(): {"sha256": sha256(root / ENTITIES)},
        },
        "affected_evidence_count": before["affected_evidence_count"],
        "affected_entity_count": before["affected_entity_count"],
        "affected_evidence_ids": before["affected_evidence_ids"],
        "raw_source_strings_preserved": True,
        "new_evidence_tier": "T3",
        "new_review_status": "pending",
    }
    manifest_path = snapshot_dir / "remediation_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.check:
        result = plan(root)
        print(
            json.dumps(
                {
                    "affected_evidence_count": result["affected_evidence_count"],
                    "affected_entity_count": result["affected_entity_count"],
                    "unremediated_residue_count": len(result["unremediated_residue"]),
                    "affected_evidence_ids": result["affected_evidence_ids"],
                },
                indent=2,
            )
        )
        return 1 if result["unremediated_residue"] else 0
    print(json.dumps(apply(root), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
