from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

try:
    from tools.operator_corpus_common import (
        canonical_json,
        csv_rows,
        expected_outputs,
        load_sources,
        safe_relative_path,
        sha256_bytes,
        sha256_file,
        source_definition_digest,
        source_ids_digest,
        validate_receipt,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution fallback
    from operator_corpus_common import (  # type: ignore[no-redef]
        canonical_json,
        csv_rows,
        expected_outputs,
        load_sources,
        safe_relative_path,
        sha256_bytes,
        sha256_file,
        source_definition_digest,
        source_ids_digest,
        validate_receipt,
    )

ASSEMBLY_SCHEMA_VERSION = "moneysweep.operator_workspace_assembly/v1"
RECEIPT_SCHEMA_VERSION = "moneysweep.operator_evidence/v1"


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _receipt_candidates(artifacts_root: Path) -> list[tuple[Path, dict[str, Any]]]:
    found: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(artifacts_root.rglob("*.json")):
        payload = _load_json(path)
        if payload and payload.get("schema_version") == RECEIPT_SCHEMA_VERSION:
            found.append((path, payload))
    return found


def _declared_for_source(source: dict[str, Any], rel: str) -> bool:
    for declared in expected_outputs(source):
        if rel == declared or (declared.endswith("/") and rel.startswith(declared)):
            return True
    return False


def _artifact_matches(
    artifacts_root: Path,
    rel: str,
    expected_sha: str,
    expected_bytes: int,
    expected_rows: int | None,
) -> list[Path]:
    name = Path(rel).name
    matches: list[Path] = []
    for candidate in artifacts_root.rglob(name):
        if not candidate.is_file():
            continue
        normalized = candidate.as_posix()
        if not (normalized.endswith("/" + rel) or candidate.relative_to(artifacts_root).as_posix() == rel):
            continue
        if candidate.stat().st_size != expected_bytes:
            continue
        if sha256_file(candidate) != expected_sha:
            continue
        if csv_rows(candidate, logical_path=rel) != expected_rows:
            continue
        matches.append(candidate)
    return sorted(matches)


def assemble(
    *,
    root: Path,
    artifacts_root: Path,
    workspace_root: Path,
) -> dict[str, Any]:
    root = root.resolve()
    artifacts_root = artifacts_root.resolve()
    workspace_root = workspace_root.resolve()
    if not artifacts_root.is_dir():
        raise RuntimeError(f"artifact root does not exist: {artifacts_root}")

    sources, registry_paths = load_sources(root)
    source_by_id = {str(source["source_id"]): source for source in sources}
    registry_digest = source_ids_digest(sources)
    candidates = _receipt_candidates(artifacts_root)
    if not candidates:
        raise RuntimeError(f"no standardized operator evidence receipts found below {artifacts_root}")

    grouped: dict[str, list[tuple[Path, dict[str, Any]]]] = {}
    blockers: list[str] = []
    rejected: list[dict[str, Any]] = []
    for path, receipt in candidates:
        source_id = str(receipt.get("source_id", "")).strip()
        errors = validate_receipt(receipt)
        source = source_by_id.get(source_id)
        if source is None:
            errors.append("source_id_not_registered")
        else:
            registry = receipt.get("registry")
            registry = registry if isinstance(registry, dict) else {}
            if registry.get("source_ids_sha256") != registry_digest:
                errors.append("registry_digest_mismatch")
            if registry.get("source_definition_sha256") != source_definition_digest(source):
                errors.append("source_definition_digest_mismatch")
            for output in receipt.get("outputs") or []:
                if not isinstance(output, dict):
                    continue
                rel = str(output.get("path") or "")
                if rel and not _declared_for_source(source, rel):
                    errors.append(f"undeclared_output:{rel}")
        if errors:
            rejected.append(
                {
                    "path": str(path),
                    "source_id": source_id,
                    "errors": sorted(set(errors)),
                }
            )
            blockers.append(f"{source_id or '<unknown>'}:invalid_receipt")
            continue
        grouped.setdefault(source_id, []).append((path, receipt))

    if workspace_root.exists():
        shutil.rmtree(workspace_root)
    receipts_dir = workspace_root / "receipts"
    receipts_dir.mkdir(parents=True, exist_ok=True)

    source_rows: list[dict[str, Any]] = []
    output_claims: dict[str, str] = {}
    for source_id in sorted(grouped):
        rows = grouped[source_id]
        identities: dict[str, list[tuple[Path, dict[str, Any]]]] = {}
        for path, receipt in rows:
            identity = sha256_bytes(canonical_json(receipt))
            identities.setdefault(identity, []).append((path, receipt))
        if len(identities) != 1:
            blockers.append(f"{source_id}:conflicting_receipts")
            source_rows.append(
                {
                    "source_id": source_id,
                    "status": "CONFLICT",
                    "receipt_count": len(rows),
                    "receipt_identity_count": len(identities),
                    "promoted_outputs": [],
                }
            )
            continue

        receipt_identity, identical_rows = next(iter(identities.items()))
        receipt = identical_rows[0][1]
        source = source_by_id[source_id]
        promoted: list[dict[str, Any]] = []
        source_blockers: list[str] = []
        for output in receipt.get("outputs") or []:
            rel = safe_relative_path(str(output["path"])).as_posix()
            expected_sha = str(output["sha256"])
            expected_bytes = int(output["bytes"])
            expected_rows = output.get("rows")
            prior = output_claims.get(rel)
            if prior is not None and prior != source_id:
                source_blockers.append(f"cross_source_output_collision:{rel}:{prior}")
                continue
            matches = _artifact_matches(
                artifacts_root,
                rel,
                expected_sha,
                expected_bytes,
                expected_rows,
            )
            if not matches:
                source_blockers.append(f"artifact_bytes_missing:{rel}")
                continue
            target = workspace_root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(matches[0], target)
            if sha256_file(target) != expected_sha or target.stat().st_size != expected_bytes:
                source_blockers.append(f"promoted_copy_revalidation_failed:{rel}")
                target.unlink(missing_ok=True)
                continue
            if csv_rows(target, logical_path=rel) != expected_rows:
                source_blockers.append(f"promoted_copy_rows_mismatch:{rel}")
                target.unlink(missing_ok=True)
                continue
            output_claims[rel] = source_id
            promoted.append(
                {
                    "path": rel,
                    "sha256": expected_sha,
                    "bytes": expected_bytes,
                    "rows": expected_rows,
                    "artifact_copy_count": len(matches),
                }
            )

        if source_blockers:
            blockers.extend(f"{source_id}:{item}" for item in source_blockers)
            status = "BLOCKED"
        elif len(promoted) != len(receipt.get("outputs") or []):
            blockers.append(f"{source_id}:receipt_output_count_mismatch")
            status = "BLOCKED"
        else:
            receipt_path = receipts_dir / f"{source_id}.json"
            receipt_path.write_text(
                json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            status = "ASSEMBLED"

        source_rows.append(
            {
                "source_id": source_id,
                "status": status,
                "receipt_count": len(rows),
                "receipt_identity": receipt_identity,
                "receipt_identity_count": 1,
                "promoted_outputs": promoted,
                "blockers": sorted(set(source_blockers)),
            }
        )

    manifest = {
        "schema_version": ASSEMBLY_SCHEMA_VERSION,
        "registry": {
            "total_sources": len(sources),
            "source_ids_sha256": registry_digest,
            "registry_paths": registry_paths,
        },
        "discovered_receipt_files": len(candidates),
        "accepted_source_ids": sorted(grouped),
        "assembled_source_count": sum(row["status"] == "ASSEMBLED" for row in source_rows),
        "workspace_output_count": len(output_claims),
        "authority_asserted": False,
        "policy": {
            "assembly_is_operator_authority": False,
            "conflicting_receipts_fail_closed": True,
            "cross_source_output_collisions_fail_closed": True,
            "all_promoted_bytes_rehashed": True,
            "corpus_verification_required_after_assembly": True,
        },
        "sources": source_rows,
        "rejected_receipts": rejected,
        "blockers": sorted(set(blockers)),
    }
    workspace_root.mkdir(parents=True, exist_ok=True)
    manifest_path = workspace_root / "assembly_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Converge standardized public/keyless/credentialed evidence artifacts into one non-authoritative operator workspace."
    )
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--artifacts-root", type=Path, required=True)
    parser.add_argument(
        "--workspace-root",
        type=Path,
        default=Path("build/operator-workspace"),
    )
    args = parser.parse_args()
    manifest = assemble(
        root=args.root,
        artifacts_root=args.artifacts_root,
        workspace_root=args.workspace_root,
    )
    print(
        json.dumps(
            {
                "discovered_receipt_files": manifest["discovered_receipt_files"],
                "assembled_source_count": manifest["assembled_source_count"],
                "workspace_output_count": manifest["workspace_output_count"],
                "blocker_count": len(manifest["blockers"]),
                "authority_asserted": False,
            },
            sort_keys=True,
        )
    )
    return 0 if not manifest["blockers"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
