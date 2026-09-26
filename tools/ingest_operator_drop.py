from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.config import setup_logging
from scripts.run_automatable_sources import (
    _bind_legacy_config_to_workspace,
    run_one,
)
from tools.operator_corpus_common import (
    expected_outputs,
    load_sources,
    safe_relative_path,
    sha256_file,
)
from tools.write_operator_evidence_receipt import build_receipt

DROP_SCHEMA_VERSION = "moneysweep.operator_drop/v1"
REPORT_SCHEMA_VERSION = "moneysweep.operator_drop_ingestion/v1"


def _parse_datetime(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _hex64(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    allowed = {"schema_version", "source_id", "obtained_at", "provenance", "files"}
    extra = sorted(set(manifest) - allowed)
    if extra:
        errors.append("unexpected_top_level_keys:" + ",".join(extra))
    if manifest.get("schema_version") != DROP_SCHEMA_VERSION:
        errors.append("schema_version_mismatch")
    if not isinstance(manifest.get("source_id"), str) or not str(manifest.get("source_id")).strip():
        errors.append("source_id_missing")
    if not _parse_datetime(manifest.get("obtained_at")):
        errors.append("obtained_at_invalid")

    provenance = manifest.get("provenance")
    if not isinstance(provenance, dict):
        errors.append("provenance_missing")
        provenance = {}
    allowed_provenance = {
        "source_url",
        "retrieval_method",
        "snapshot_as_of",
        "notes",
    }
    extra_provenance = sorted(set(provenance) - allowed_provenance)
    if extra_provenance:
        errors.append("unexpected_provenance_keys:" + ",".join(extra_provenance))
    for key in ("source_url", "retrieval_method"):
        if not isinstance(provenance.get(key), str) or not provenance.get(key, "").strip():
            errors.append(f"provenance_{key}_missing")

    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        errors.append("files_missing")
        files = []
    seen: set[str] = set()
    for index, item in enumerate(files):
        prefix = f"file_{index}"
        if not isinstance(item, dict):
            errors.append(f"{prefix}_invalid")
            continue
        extra_item = sorted(set(item) - {"path", "sha256", "bytes"})
        if extra_item:
            errors.append(f"{prefix}_unexpected_keys:" + ",".join(extra_item))
        value = item.get("path")
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{prefix}_path_missing")
        else:
            try:
                rel = safe_relative_path(value).as_posix()
            except ValueError:
                errors.append(f"{prefix}_path_unsafe")
            else:
                if rel in seen:
                    errors.append(f"{prefix}_path_duplicate")
                seen.add(rel)
        if not _hex64(item.get("sha256")):
            errors.append(f"{prefix}_sha256_invalid")
        size = item.get("bytes")
        if not isinstance(size, int) or isinstance(size, bool) or size < 1:
            errors.append(f"{prefix}_bytes_invalid")
    return sorted(set(errors))


def _present_outputs(workspace: Path, source: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for expected in expected_outputs(source):
        target = workspace / expected
        if expected.endswith("/"):
            if target.is_dir():
                paths.extend(
                    item.relative_to(workspace).as_posix()
                    for item in sorted(target.rglob("*"))
                    if item.is_file()
                )
        elif target.is_file():
            paths.append(Path(expected).as_posix())
    return sorted(set(paths))


def ingest(
    *,
    registry_root: Path,
    workspace: Path,
    bundle_root: Path,
    receipts_dir: Path,
    producer_sha: str,
) -> dict[str, Any]:
    registry_root = registry_root.resolve()
    workspace = workspace.resolve()
    bundle_root = bundle_root.resolve()
    receipts_dir = receipts_dir.resolve()

    manifest_path = bundle_root / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError(f"operator drop manifest missing: {manifest_path}")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("operator drop manifest must contain an object")
    contract_errors = validate_manifest(payload)
    if contract_errors:
        raise RuntimeError("invalid operator drop manifest: " + "; ".join(contract_errors))

    sources, _ = load_sources(registry_root)
    source_by_id = {str(source["source_id"]): source for source in sources}
    source_id = str(payload["source_id"]).strip()
    source = source_by_id.get(source_id)
    if source is None:
        raise RuntimeError(f"operator drop source is not registered: {source_id}")

    ingest_script = str(
        source.get("authorized_manual_ingest_script") or source.get("producer_script") or ""
    ).strip()
    drop_dir_value = str(
        source.get("authorized_manual_drop_dir") or source.get("manual_drop_dir") or ""
    ).strip()
    if not ingest_script or not drop_dir_value:
        raise RuntimeError(f"{source_id}: no registered manual ingest boundary")
    drop_dir = safe_relative_path(drop_dir_value)
    if not (
        str(source.get("authentication") or "") == "manual_export"
        or source.get("authorized_manual_ingest_script")
    ):
        raise RuntimeError(f"{source_id}: source is not authorized for operator-drop ingestion")

    files_root = bundle_root / "files"
    declared: dict[str, dict[str, Any]] = {
        safe_relative_path(str(item["path"])).as_posix(): item for item in payload["files"]
    }
    actual = (
        {
            path.relative_to(files_root).as_posix()
            for path in files_root.rglob("*")
            if path.is_file()
        }
        if files_root.is_dir()
        else set()
    )
    if set(declared) != actual:
        missing = sorted(set(declared) - actual)
        undeclared = sorted(actual - set(declared))
        raise RuntimeError(
            f"operator drop file inventory mismatch: missing={missing}; undeclared={undeclared}"
        )

    staged_inputs: list[str] = []
    input_evidence: list[dict[str, Any]] = []
    for rel, declared_item in sorted(declared.items()):
        source_file = files_root / rel
        actual_sha = sha256_file(source_file)
        actual_bytes = source_file.stat().st_size
        if actual_sha != declared_item["sha256"]:
            raise RuntimeError(f"operator drop sha256 mismatch: {rel}")
        if actual_bytes != declared_item["bytes"]:
            raise RuntimeError(f"operator drop byte-count mismatch: {rel}")

        staged_rel = (drop_dir / rel).as_posix()
        staged = workspace / staged_rel
        staged.parent.mkdir(parents=True, exist_ok=True)
        if staged.exists() and (not staged.is_file() or sha256_file(staged) != actual_sha):
            raise RuntimeError(
                f"operator drop conflicts with existing workspace bytes: {staged_rel}"
            )
        if not staged.exists():
            shutil.copy2(source_file, staged)
        if sha256_file(staged) != actual_sha:
            raise RuntimeError(f"operator drop staged hash mismatch: {staged_rel}")
        staged_inputs.append(staged_rel)
        input_evidence.append(
            {
                "bundle_path": rel,
                "staged_path": staged_rel,
                "sha256": actual_sha,
                "bytes": actual_bytes,
            }
        )

    logger = setup_logging("ingest_operator_drop")
    _bind_legacy_config_to_workspace(workspace)
    ingest_source = dict(source)
    ingest_source["producer_script"] = ingest_script
    runner_result = run_one(workspace, ingest_source, logger)

    outputs = _present_outputs(workspace, source)
    receipt_path = None
    receipt_error = None
    if outputs:
        provenance = payload["provenance"]
        try:
            receipt = build_receipt(
                root=workspace,
                registry_root=registry_root,
                source_id=source_id,
                inputs=staged_inputs,
                outputs=outputs,
                producer_sha=producer_sha,
                producer=ingest_script,
                source_url=str(provenance["source_url"]),
                completed_at=datetime.now().astimezone().isoformat(),
                coverage_contract_pass=False,
            )
        except Exception as exc:  # noqa: BLE001 - preserve exact receipt blocker
            receipt_error = f"{type(exc).__name__}:{exc}"
        else:
            receipts_dir.mkdir(parents=True, exist_ok=True)
            receipt_path = receipts_dir / f"{source_id}.json"
            receipt_path.write_text(
                json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "source_id": source_id,
        "ingest_script": ingest_script,
        "drop_dir": drop_dir.as_posix(),
        "manifest_sha256": sha256_file(manifest_path),
        "input_files": input_evidence,
        "runner_result": runner_result,
        "outputs": outputs,
        "receipt_path": (receipt_path.as_posix() if receipt_path is not None else None),
        "receipt_error": receipt_error,
        "materialization_candidate": receipt_path is not None,
        "coverage_contract_pass": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate and ingest a hashed operator-drop bundle fail-closed."
    )
    parser.add_argument("--registry-root", type=Path, default=Path("."))
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--receipts-dir", type=Path, required=True)
    parser.add_argument("--producer-sha", required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/operator_drop_ingestion.json"),
    )
    args = parser.parse_args()

    report = ingest(
        registry_root=args.registry_root,
        workspace=args.workspace,
        bundle_root=args.bundle_root,
        receipts_dir=args.receipts_dir,
        producer_sha=args.producer_sha,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["materialization_candidate"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
