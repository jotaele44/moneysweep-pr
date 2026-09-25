#!/usr/bin/env python3
"""Build a current-denominator materialization/lineage audit.

Checkout-visible evidence is useful for reconciliation, but production provenance
is awarded only by a cryptographically bound operator-corpus manifest plus a
successful full verification receipt. A CLI assertion alone can never make a
checkout authoritative, and the mounted corpus is revalidated before authority
is consumed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

try:
    from tools.operator_corpus_common import manifest_digest, source_ids_digest
    from tools.verify_operator_corpus import verify as verify_operator_corpus
except ModuleNotFoundError:  # pragma: no cover - direct script execution fallback
    from operator_corpus_common import manifest_digest, source_ids_digest  # type: ignore[no-redef]
    from verify_operator_corpus import verify as verify_operator_corpus  # type: ignore[no-redef]


def _row_count(path: Path) -> int | None:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            return max(sum(1 for _ in csv.reader(fh)) - 1, 0)
    except (OSError, UnicodeDecodeError, csv.Error):
        return None


def _sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _as_paths(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value]


def _load_sources(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    registry_path = root / "registries/source_registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    sources = list(registry.get("sources") or [])
    registry_paths = ["registries/source_registry.yaml"]

    extension_dir = root / "registries/source_registry_extensions"
    if extension_dir.exists():
        for path in sorted(extension_dir.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            extension_sources = payload.get("sources")
            if extension_sources is None:
                continue
            if not isinstance(extension_sources, list):
                raise RuntimeError(f"Source registry extension must contain a sources list: {path}")
            sources.extend(extension_sources)
            registry_paths.append(path.relative_to(root).as_posix())

    source_ids = [str(source.get("source_id", "")).strip() for source in sources]
    duplicates = sorted({source_id for source_id in source_ids if source_ids.count(source_id) > 1})
    if duplicates:
        raise RuntimeError(
            "Duplicate source IDs across core/extension registries: " + ", ".join(duplicates)
        )
    if any(not source_id for source_id in source_ids):
        raise RuntimeError("Core/extension source registry contains an empty source_id")
    return registry, sources, registry_paths


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON evidence must contain an object: {path}")
    return payload


def _resolve_authority(
    *,
    root: Path,
    sources: list[dict[str, Any]],
    registry_paths: list[str],
    legacy_authority_requested: bool,
    manifest_path: Path | None,
    verification_path: Path | None,
) -> tuple[bool, Path, dict[str, Any]]:
    blockers: list[str] = []
    evidence: dict[str, Any] = {
        "legacy_authority_requested": legacy_authority_requested,
        "manifest_path": None,
        "manifest_sha256": None,
        "verification_path": None,
        "verification_sha256": None,
        "corpus_id": None,
        "content_revalidation": None,
        "authority_blockers": blockers,
    }

    if manifest_path is None and verification_path is None:
        if legacy_authority_requested:
            blockers.append("bare_authority_assertion_not_evidence")
        else:
            blockers.append("operator_corpus_proof_not_supplied")
        return False, root, evidence
    if manifest_path is None or verification_path is None:
        blockers.append("operator_corpus_manifest_and_verification_required_together")
        return False, root, evidence

    manifest_path = manifest_path.resolve()
    verification_path = verification_path.resolve()
    evidence.update(
        {
            "manifest_path": str(manifest_path),
            "manifest_sha256": _sha256(manifest_path),
            "verification_path": str(verification_path),
            "verification_sha256": _sha256(verification_path),
        }
    )
    if not manifest_path.exists():
        blockers.append("operator_corpus_manifest_missing")
    if not verification_path.exists():
        blockers.append("operator_corpus_verification_missing")
    if blockers:
        return False, root, evidence

    try:
        manifest = _load_json(manifest_path)
        verification = _load_json(verification_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RuntimeError):
        blockers.append("operator_corpus_proof_unreadable")
        return False, root, evidence

    current_digest = source_ids_digest(sources)
    current_required = sum(source.get("required") is True for source in sources)
    claimed_corpus_id = manifest.get("corpus_id")
    computed_corpus_id = manifest_digest(manifest)
    evidence["corpus_id"] = claimed_corpus_id
    evidence["computed_corpus_id"] = computed_corpus_id
    evidence["current_source_ids_sha256"] = current_digest

    manifest_registry = manifest.get("registry")
    verification_registry = verification.get("registry")
    if not isinstance(manifest_registry, dict):
        manifest_registry = {}
        blockers.append("manifest_registry_missing")
    if not isinstance(verification_registry, dict):
        verification_registry = {}
        blockers.append("verification_registry_missing")

    if claimed_corpus_id != computed_corpus_id:
        blockers.append("corpus_id_mismatch")
    if verification.get("corpus_id") != claimed_corpus_id:
        blockers.append("verification_corpus_id_mismatch")
    if verification.get("computed_corpus_id") != claimed_corpus_id:
        blockers.append("verification_computed_corpus_id_mismatch")
    if verification.get("verified") is not True:
        blockers.append("operator_corpus_verification_not_passed")
    if verification.get("operator_corpus_authoritative") is not True:
        blockers.append("operator_corpus_verification_not_authoritative")
    if verification.get("errors") not in ([], None):
        blockers.append("operator_corpus_verification_contains_errors")
    verification_scope = verification.get("verification_scope")
    if not isinstance(verification_scope, dict) or (
        verification_scope.get("operator_snapshot_required") is not True
    ):
        blockers.append("full_operator_snapshot_verification_required")

    for label, registry_evidence in (
        ("manifest", manifest_registry),
        ("verification", verification_registry),
    ):
        if registry_evidence.get("total_sources") != len(sources):
            blockers.append(f"{label}_registry_total_mismatch")
        if registry_evidence.get("required_sources") != current_required:
            blockers.append(f"{label}_required_source_count_mismatch")
        if registry_evidence.get("source_ids_sha256") != current_digest:
            blockers.append(f"{label}_registry_digest_mismatch")
        if registry_evidence.get("registry_paths") != registry_paths:
            blockers.append(f"{label}_registry_paths_mismatch")

    snapshot = manifest.get("snapshot")
    if not isinstance(snapshot, dict) or snapshot.get("processed_inventory_complete") is not True:
        blockers.append("manifest_processed_inventory_not_complete")

    evidence_root = manifest_path.parent / "mount"
    if not evidence_root.exists() or not evidence_root.is_dir():
        blockers.append("operator_corpus_mount_missing")

    if not blockers:
        try:
            revalidation = verify_operator_corpus(
                root=root,
                corpus_root=manifest_path.parent,
                require_operator_snapshot=False,
            )
        except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
            blockers.append("operator_corpus_content_revalidation_error")
            evidence["content_revalidation"] = {
                "verified": False,
                "error_type": type(exc).__name__,
            }
        else:
            evidence["content_revalidation"] = {
                "verified": revalidation.get("verified"),
                "corpus_id": revalidation.get("corpus_id"),
                "computed_corpus_id": revalidation.get("computed_corpus_id"),
                "errors": revalidation.get("errors"),
                "mode": revalidation.get("verification_scope", {}).get("mode"),
            }
            if revalidation.get("verified") is not True:
                blockers.append("operator_corpus_content_revalidation_failed")
            if revalidation.get("corpus_id") != claimed_corpus_id:
                blockers.append("operator_corpus_revalidation_id_mismatch")
            if revalidation.get("operator_corpus_authoritative") is not False:
                blockers.append("content_revalidation_must_not_self_award_authority")

    authority = not blockers
    return authority, evidence_root if authority else root, evidence


def _owners_for_path(rel: str, declared: dict[str, list[str]]) -> list[str]:
    owners: list[str] = []
    for expected, source_ids in declared.items():
        if rel == expected or (expected.endswith("/") and rel.startswith(expected)):
            owners.extend(source_ids)
    return sorted(set(owners))


def build(
    root: Path,
    *,
    operator_corpus_authoritative: bool = False,
    operator_corpus_manifest: Path | None = None,
    operator_corpus_verification: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    registry, sources, registry_paths = _load_sources(root)
    authority, evidence_root, authority_evidence = _resolve_authority(
        root=root,
        sources=sources,
        registry_paths=registry_paths,
        legacy_authority_requested=operator_corpus_authoritative,
        manifest_path=operator_corpus_manifest,
        verification_path=operator_corpus_verification,
    )

    declared: dict[str, list[str]] = {}
    source_rows: list[dict[str, Any]] = []
    required_total = 0
    required_full = 0
    full = 0
    partial = 0
    missing = 0
    no_outputs = 0

    for source in sources:
        source_id = str(source.get("source_id", "")).strip()
        outputs = _as_paths(source.get("expected_outputs"))
        if source.get("required") is True:
            required_total += 1

        present = 0
        total_rows = 0
        unreadable = 0
        output_evidence: list[dict[str, Any]] = []
        for rel in outputs:
            declared.setdefault(rel, []).append(source_id)
            path = evidence_root / rel
            exists = path.exists()
            rows = (
                _row_count(path)
                if exists and path.is_file() and path.suffix.lower() == ".csv"
                else None
            )
            if exists:
                present += 1
            if rows is not None:
                total_rows += rows
            elif exists and path.is_file() and path.suffix.lower() == ".csv":
                unreadable += 1
            output_evidence.append(
                {
                    "path": rel,
                    "exists": exists,
                    "data_rows": rows,
                    "sha256": _sha256(path) if exists and path.is_file() else None,
                }
            )

        if not outputs:
            status = "no_outputs_declared"
            no_outputs += 1
        elif present == len(outputs):
            status = "fully_materialized"
            full += 1
            if source.get("required") is True:
                required_full += 1
        elif present:
            status = "partially_materialized"
            partial += 1
        else:
            status = "not_materialized"
            missing += 1

        source_rows.append(
            {
                "source_id": source_id,
                "family": source.get("family"),
                "required": bool(source.get("required")),
                "expected_output_count": len(outputs),
                "present_count": present,
                "local_rows": total_rows,
                "unreadable_csv_count": unreadable,
                "local_status": status,
                "outputs": output_evidence,
            }
        )

    processed = evidence_root / "data/staging/processed"
    inventory: list[dict[str, Any]] = []
    total_rows = 0
    accounted_rows = 0
    measured_orphan_rows = 0
    measured_orphan_files = 0
    if processed.exists():
        for path in sorted(processed.rglob("*.csv")):
            rel = path.relative_to(evidence_root).as_posix()
            rows = _row_count(path)
            row_count = rows if rows is not None else 0
            owners = _owners_for_path(rel, declared)
            classification = "declared" if owners else "unclaimed"
            total_rows += row_count
            if owners:
                accounted_rows += row_count
            else:
                measured_orphan_rows += row_count
                measured_orphan_files += 1
            inventory.append(
                {
                    "file": rel,
                    "rows": rows,
                    "claimed_by": owners,
                    "classification": classification,
                    "sha256": _sha256(path),
                }
            )

    certifiable_orphan_rows = measured_orphan_rows if authority else None
    certifiable_orphan_files = measured_orphan_files if authority else None
    authority_blockers = authority_evidence["authority_blockers"]

    return {
        "schema_version": "coverage_audit_v4",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "audit_scope": {
            "root": str(root),
            "evidence_root": str(evidence_root),
            "registry_path": "registries/source_registry.yaml",
            "registry_paths": registry_paths,
            "registry_schema_version": registry.get("schema_version"),
            "registry_source_ids_sha256": source_ids_digest(sources),
            "operator_corpus_authoritative": authority,
            "operator_corpus_id": authority_evidence.get("corpus_id"),
            "operator_corpus_proof": authority_evidence,
            "authority_blockers": authority_blockers,
            "corpus_class": (
                "authoritative_operator_corpus" if authority else "checkout_visible_files_only"
            ),
            "warning": (
                None
                if authority
                else "Cryptographically verified operator-corpus proof is absent or invalid; G8 must remain blocked."
            ),
        },
        "local_truth_summary": {
            "total_sources": len(sources),
            "required_sources": required_total,
            "fully_materialized": full,
            "partially_materialized": partial,
            "not_materialized": missing,
            "no_outputs_declared": no_outputs,
            "required_fully_materialized": required_full,
        },
        "processed_file_inventory": {
            "processed_dir": "data/staging/processed",
            "total_csv_files": len(inventory),
            "total_rows_on_disk": total_rows,
            "registry_accounted_rows": accounted_rows,
            "measured_orphan_rows": measured_orphan_rows,
            "measured_orphan_file_count": measured_orphan_files,
            "orphan_rows": certifiable_orphan_rows,
            "orphan_file_count": certifiable_orphan_files,
            "files": inventory,
        },
        "sources": source_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default="reports/materialization_coverage_audit.current.json")
    parser.add_argument(
        "--operator-corpus-authoritative",
        action="store_true",
        help="Deprecated assertion only; cannot award authority without proof artifacts.",
    )
    parser.add_argument("--operator-corpus-manifest", type=Path)
    parser.add_argument("--operator-corpus-verification", type=Path)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    output = Path(args.output)
    if not output.is_absolute():
        output = Path.cwd() / output

    report = build(
        root,
        operator_corpus_authoritative=args.operator_corpus_authoritative,
        operator_corpus_manifest=args.operator_corpus_manifest,
        operator_corpus_verification=args.operator_corpus_verification,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["local_truth_summary"], sort_keys=True))
    print(
        json.dumps(
            {
                "operator_corpus_authoritative": report["audit_scope"][
                    "operator_corpus_authoritative"
                ],
                "authority_blockers": report["audit_scope"]["authority_blockers"],
                "measured_orphan_rows": report["processed_file_inventory"]["measured_orphan_rows"],
                "certifiable_orphan_rows": report["processed_file_inventory"]["orphan_rows"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
