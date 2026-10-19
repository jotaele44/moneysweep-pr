from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from scripts.download_grants import MASTER_COLUMNS
from tools.keyless_execution_plan import GRANTS_SOURCE_ID, build_grants_shard_plan
from tools.operator_corpus_common import csv_rows, safe_relative_path, sha256_file

SCHEMA_VERSION = "moneysweep.grants_shard_assembly/v1"
SUMMARY_SCHEMA_VERSION = "moneysweep.grants_download/v2"


def _load_summary(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("summary must contain a JSON object")
    return payload


def _is_within(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def assemble_grants_shards(
    *,
    artifacts_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    artifacts_root = artifacts_root.resolve()
    output_dir = output_dir.resolve()
    if output_dir == artifacts_root or output_dir in artifacts_root.parents:
        raise ValueError("output_dir may not contain or equal artifacts_root")
    if output_dir.is_symlink():
        raise ValueError("output_dir may not be a symbolic link")
    expected_shards = build_grants_shard_plan()
    expected_by_id = {str(item["shard_id"]): item for item in expected_shards}
    summary_dir = artifacts_root / "certification_out" / "grants_shards"

    errors: list[str] = []
    if not expected_shards:
        errors.append("grants_shard_plan_empty")
    if len(expected_by_id) != len(expected_shards):
        errors.append("duplicate_expected_shard_id")
    summaries: dict[str, tuple[Path, dict[str, Any]]] = {}
    for path in sorted(summary_dir.glob("*.json")) if summary_dir.is_dir() else []:
        try:
            summary = _load_summary(path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"summary_unreadable:{path.name}:{type(exc).__name__}")
            continue
        shard_id = path.stem
        if shard_id in summaries:
            errors.append(f"duplicate_shard_summary:{shard_id}")
            continue
        summaries[shard_id] = (path, summary)

    expected_ids = set(expected_by_id)
    actual_ids = set(summaries)
    for shard_id in sorted(expected_ids - actual_ids):
        errors.append(f"missing_shard_summary:{shard_id}")
    for shard_id in sorted(actual_ids - expected_ids):
        errors.append(f"unexpected_shard_summary:{shard_id}")

    copied_files: list[dict[str, Any]] = []
    claimed_paths: dict[str, str] = {}
    for shard_id in sorted(expected_ids & actual_ids):
        _, summary = summaries[shard_id]
        expected = expected_by_id[shard_id]
        expected_paths = {
            f"data/staging/raw/grants/{expected['pass_name']}_fy{fy}.csv"
            for fy in range(int(expected["fy_start"]), int(expected["fy_end"]) + 1)
        }

        if summary.get("schema_version") != SUMMARY_SCHEMA_VERSION:
            errors.append(f"{shard_id}:summary_schema_mismatch")
        for key in ("only_pass", "fy_start", "fy_end"):
            expected_value = expected["pass_name"] if key == "only_pass" else expected[key]
            if summary.get(key) != expected_value:
                errors.append(f"{shard_id}:{key}_mismatch")
        if summary.get("master_built") is not False:
            errors.append(f"{shard_id}:partial_master_must_not_be_built")
        producer_errors = summary.get("errors")
        if not isinstance(producer_errors, list):
            errors.append(f"{shard_id}:producer_errors_invalid")
        else:
            for item in producer_errors:
                errors.append(f"{shard_id}:producer_error:{item}")
        if summary.get("missing_raw_files"):
            errors.append(f"{shard_id}:summary_reports_missing_raw_files")
        summarized_expected = summary.get("expected_raw_files")
        if (
            not isinstance(summarized_expected, list)
            or any(not isinstance(item, str) for item in summarized_expected)
            or len(summarized_expected) != len(set(summarized_expected))
            or set(summarized_expected) != expected_paths
        ):
            errors.append(f"{shard_id}:expected_raw_file_set_mismatch")

        raw_records = summary.get("raw_files")
        if not isinstance(raw_records, list):
            errors.append(f"{shard_id}:raw_file_manifest_missing")
            continue
        record_by_path: dict[str, dict[str, Any]] = {}
        for record in raw_records:
            if not isinstance(record, dict):
                errors.append(f"{shard_id}:raw_file_record_invalid")
                continue
            path_value = str(record.get("path") or "")
            try:
                relative = safe_relative_path(path_value).as_posix()
            except ValueError:
                errors.append(f"{shard_id}:raw_file_path_unsafe:{path_value}")
                continue
            if relative in record_by_path:
                errors.append(f"{shard_id}:duplicate_raw_file_record:{relative}")
                continue
            record_by_path[relative] = record

        actual_paths = set(record_by_path)
        for relative in sorted(expected_paths - actual_paths):
            errors.append(f"{shard_id}:raw_file_record_missing:{relative}")
        for relative in sorted(actual_paths - expected_paths):
            errors.append(f"{shard_id}:unexpected_raw_file_record:{relative}")

        for relative in sorted(expected_paths & actual_paths):
            record = record_by_path[relative]
            previous = claimed_paths.get(relative)
            if previous is not None:
                errors.append(f"raw_file_claimed_by_multiple_shards:{relative}")
                continue
            claimed_paths[relative] = shard_id
            source = artifacts_root / relative
            if not _is_within(artifacts_root, source) or source.is_symlink():
                errors.append(f"{shard_id}:raw_file_unsafe:{relative}")
                continue
            if not source.is_file():
                errors.append(f"{shard_id}:raw_file_missing:{relative}")
                continue
            file_errors = 0
            digest = sha256_file(source)
            if record.get("sha256") != digest:
                errors.append(f"{shard_id}:raw_file_sha256_mismatch:{relative}")
                file_errors += 1
            if record.get("bytes") != source.stat().st_size:
                errors.append(f"{shard_id}:raw_file_bytes_mismatch:{relative}")
                file_errors += 1
            observed_rows = csv_rows(source)
            if record.get("rows") != observed_rows:
                errors.append(f"{shard_id}:raw_file_rows_mismatch:{relative}")
                file_errors += 1
            if record.get("columns") != MASTER_COLUMNS:
                errors.append(f"{shard_id}:raw_file_schema_mismatch:{relative}")
                file_errors += 1
            if file_errors:
                continue
            copied_files.append(
                {
                    "path": relative,
                    "sha256": digest,
                    "bytes": source.stat().st_size,
                    "rows": record.get("rows"),
                    "shard_id": shard_id,
                }
            )

    expected_file_count = sum(
        int(shard["fy_end"]) - int(shard["fy_start"]) + 1 for shard in expected_shards
    )
    if len(claimed_paths) != expected_file_count:
        errors.append(f"raw_file_count_mismatch:{len(claimed_paths)}!={expected_file_count}")

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if not errors:
        for record in copied_files:
            relative = Path(str(record["path"]))
            source = artifacts_root / relative
            target = output_dir / relative.name
            shutil.copy2(source, target)
            if sha256_file(target) != record["sha256"]:
                errors.append(f"post_copy_sha256_mismatch:{relative.as_posix()}")

    if errors:
        shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

    return {
        "schema_version": SCHEMA_VERSION,
        "source_id": GRANTS_SOURCE_ID,
        "expected_shards": len(expected_shards),
        "observed_shards": len(actual_ids & expected_ids),
        "expected_raw_files": expected_file_count,
        "verified_raw_files": len(copied_files),
        "copied_raw_files": len(list(output_dir.glob("*.csv"))),
        "shard_ids": sorted(actual_ids & expected_ids),
        "files": sorted(copied_files, key=lambda item: str(item["path"])),
        "errors": sorted(set(errors)),
        "complete": not errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify and assemble grants fiscal-year shards.")
    parser.add_argument("--artifacts-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    report = assemble_grants_shards(
        artifacts_root=args.artifacts_root,
        output_dir=args.output_dir,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
