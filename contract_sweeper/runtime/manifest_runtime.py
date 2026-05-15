"""Manifest writer for ingested datasets.

For every staged file under `data/staging/` (and any explicit per-source
artifact), this module records:
  - row_count, column_count, columns
  - sha256 (via file_hash_runtime)
  - size_bytes, mtime, ingestion_timestamp_utc
  - source_system, schema_version, source_url, source_path
  - year_coverage_pct, expected_years, actual_years
  - field_completeness_pct_by_column
  - duplicate_rate (when a primary_key is declared)
  - entity_match_rate_pct (when entity-name columns are present)
  - validation_status: present | empty_or_header_only | error
  - manual_review_required + reason

Outputs:
  - data/manifests/<source_id>/<utc_timestamp>.json     (per-ingest snapshot)
  - data/manifests/source_manifest.json                 (rolling canonical)
  - data/manifests/source_manifest.csv                  (flat view)

Stdlib only.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from contract_sweeper.runtime.file_hash_runtime import sha256_file
from contract_sweeper.runtime.name_normalization import normalize_name
from contract_sweeper.runtime.source_registry import (
    REPO_ROOT,
    all_sources,
    source_by_id,
)

DATA_EXTS = frozenset({".csv", ".json", ".parquet", ".gexf", ".graphml", ".geojson", ".jsonl"})

# Fields that look like entity names; used to compute entity_match_rate.
_ENTITY_NAME_FIELDS = (
    "recipient_name",
    "vendor_name",
    "award_recipient_name",
    "prime_recipient_name",
    "sub_recipient_name",
    "client_name",
    "registrant_name",
    "contractor",
    "contratista",
    "applicant",
    "entity_name",
)

_YEAR_FIELDS = (
    "fiscal_year",
    "award_date",
    "action_date",
    "filing_year",
    "report_year",
    "year",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _csv_profile(path: Path) -> dict[str, Any]:
    out: dict[str, Any] = {
        "row_count": 0,
        "column_count": 0,
        "columns": [],
        "empty_or_header_only": True,
    }
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, [])
            out["columns"] = header
            out["column_count"] = len(header)
            for _ in reader:
                out["row_count"] += 1
        out["empty_or_header_only"] = out["row_count"] == 0
    except Exception as exc:  # pragma: no cover — defensive
        out["error"] = str(exc)
        out["empty_or_header_only"] = True
    return out


def _csv_completeness_and_matches(path: Path) -> dict[str, Any]:
    """Per-column completeness + entity-name match counts."""
    fields: list[str] = []
    seen: Counter[str] = Counter()
    nonempty: Counter[str] = Counter()
    entity_total = 0
    entity_normalized = 0
    years: set[int] = set()
    duplicate_rows = 0
    pk_keys: set[str] = set()
    pk_field = None
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fields = list(reader.fieldnames or [])
            # Pick a pk-ish field if available. More-specific fields first so that
            # FEMA PA (pw_number), project-level sources, and subaward tables do not
            # accidentally use a shared parent key (e.g. award_id) as their pk and
            # produce spurious duplicate_rate > 1 readings.
            for cand in (
                "pw_number",
                "project_number",
                "project_id",
                "subaward_number",
                "subaward_id",
                "generated_unique_award_id",
                "unique_award_key",
                "contract_number",
                "award_id",
            ):
                if cand in fields:
                    pk_field = cand
                    break
            for row in reader:
                for k in fields:
                    seen[k] += 1
                    if (row.get(k) or "").strip():
                        nonempty[k] += 1
                # entity-name match rate proxy: how many entity-name cells normalize to non-empty.
                for ef in _ENTITY_NAME_FIELDS:
                    if ef in row and (row.get(ef) or "").strip():
                        entity_total += 1
                        if normalize_name(row.get(ef)):
                            entity_normalized += 1
                # year extraction
                for yf in _YEAR_FIELDS:
                    v = row.get(yf)
                    if not v:
                        continue
                    try:
                        years.add(int(str(v)[:4]))
                    except ValueError:
                        continue
                if pk_field:
                    key = (row.get(pk_field) or "").strip()
                    if key:
                        if key in pk_keys:
                            duplicate_rows += 1
                        else:
                            pk_keys.add(key)
    except Exception as exc:  # pragma: no cover
        return {"error": str(exc)}
    field_completeness = {
        k: (nonempty[k] / seen[k]) if seen[k] else 0.0 for k in fields
    }
    return {
        "field_completeness_pct_by_column": field_completeness,
        "entity_match_rate_pct": (entity_normalized / entity_total) if entity_total else None,
        "actual_years": sorted(years),
        # Rate = duplicate rows / total rows scanned (not / unique-key count).
        # The old formula (/ len(pk_keys)) can exceed 1.0 when a pk field is shared
        # across many rows (e.g. FEMA PA award_id shared by ~1 000 project rows).
        "duplicate_rate": (duplicate_rows / (duplicate_rows + len(pk_keys))) if pk_keys else 0.0,
        "pk_field": pk_field,
    }


def _json_profile(path: Path) -> dict[str, Any]:
    out: dict[str, Any] = {"row_count": None, "column_count": None, "empty_or_header_only": False}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            out["row_count"] = len(data)
            if data and isinstance(data[0], dict):
                out["column_count"] = len(data[0])
            out["empty_or_header_only"] = len(data) == 0
        elif isinstance(data, dict):
            out["row_count"] = len(data)
            out["column_count"] = len(data)
            out["empty_or_header_only"] = len(data) == 0
    except Exception as exc:  # pragma: no cover
        out["error"] = str(exc)
    return out


def _safe_all_sources(root: Path) -> list[dict[str, Any]]:
    """Return registry sources, or [] if the registry isn't readable under root."""
    try:
        return all_sources(root)
    except (FileNotFoundError, OSError):
        return []


def _infer_source_id(path: Path, sources: list[dict[str, Any]]) -> str:
    """Best-effort source_id inference for files not yet bound to a producer."""
    name = path.name.lower()
    for src in sources:
        for out in src.get("expected_outputs", []) or []:
            if Path(out).name.lower() == name:
                return src["source_id"]
    # heuristic fallbacks
    for tok, sid in [
        ("fema", "fema_pa_openfema_v2"),
        ("cdbg", "hud_cdbg_dr_public"),
        ("drgr", "hud_drgr_authorized"),
        ("subaward", "usaspending_subawards"),
        ("fsrs", "fsrs_subawards"),
        ("sam", "sam_entities"),
        ("uei", "sam_entities"),
        ("emma", "emma_bonds"),
        ("msrb", "msrb_rtrs_trades"),
        ("lda", "lda"),
        ("cabildero", "pr_cabilderos"),
        ("fec", "fec"),
        ("cor3", "cor3"),
        ("prasa", "prasa"),
        ("contralor", "oficina_contralor"),
        ("all_awards", "usaspending_prime"),
        ("contracts_master", "usaspending_prime"),
    ]:
        if tok in name:
            return sid
    return "unknown"


def profile_file(
    path: Path,
    *,
    root: Path,
    source_id: str | None = None,
    source_url: str | None = None,
    schema_version: str | None = None,
    expected_years: list[int] | None = None,
) -> dict[str, Any]:
    rel = path.relative_to(root).as_posix()
    sid = source_id or _infer_source_id(path, _safe_all_sources(root))
    item: dict[str, Any] = {
        "file_name": path.name,
        "relative_path": rel,
        "extension": path.suffix.lower(),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "ingestion_timestamp_utc": _now_iso(),
        "source_system": sid,
        "source_url": source_url,
        "schema_version": schema_version,
        "expected_years": expected_years,
    }
    if path.suffix.lower() == ".csv":
        item.update(_csv_profile(path))
        if not item.get("empty_or_header_only"):
            item.update(_csv_completeness_and_matches(path))
    elif path.suffix.lower() in (".json", ".jsonl"):
        item.update(_json_profile(path))
    else:
        item.update({"row_count": None, "column_count": None, "empty_or_header_only": path.stat().st_size == 0})

    # year coverage %
    actual = item.get("actual_years") or []
    expected = expected_years or []
    if expected:
        item["year_coverage_pct"] = (
            len(set(actual) & set(expected)) / len(set(expected)) if expected else None
        )
    else:
        item["year_coverage_pct"] = None

    item["validation_status"] = (
        "empty_or_header_only"
        if item.get("empty_or_header_only")
        else ("present" if "error" not in item else "error")
    )
    return item


def scan_repo(root: Path) -> list[dict[str, Any]]:
    """Profile every data file under `data/` and `registries/`."""
    files: list[dict[str, Any]] = []
    for base in [root / "data", root / "registries"]:
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if (
                p.is_file()
                and p.suffix.lower() in DATA_EXTS
                and not p.name.startswith("._")
            ):
                try:
                    files.append(profile_file(p, root=root))
                except Exception as exc:  # pragma: no cover
                    files.append(
                        {
                            "relative_path": p.relative_to(root).as_posix(),
                            "validation_status": "error",
                            "error": str(exc),
                        }
                    )
    return sorted(files, key=lambda x: x.get("relative_path", ""))


def write_per_source_manifest(
    root: Path,
    *,
    source_id: str,
    files: list[dict[str, Any]],
) -> Path:
    """Write a `data/manifests/<source_id>/<timestamp>.json` snapshot."""
    src = source_by_id(source_id, root) or {"source_id": source_id}
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = root / "data" / "manifests" / source_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{ts}.json"
    payload = {
        "manifest_type": "per_source_ingest_snapshot",
        "schema_version": src.get("schema_version", "r5_v1"),
        "source_id": source_id,
        "source_url": src.get("endpoint_url"),
        "producer_script": src.get("producer_script"),
        "generated_at": _now_iso(),
        "file_count": len(files),
        "files": files,
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out_path


def write_canonical_manifest(root: Path, files: list[dict[str, Any]]) -> dict[str, Path]:
    """Write the rolling `data/manifests/source_manifest.json` + .csv."""
    out_dir = root / "data" / "manifests"
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "manifest_type": "canonical_source_manifest",
        "schema_version": "r5_v1",
        "generated_at": _now_iso(),
        "file_count": len(files),
        "empty_or_header_only_count": sum(1 for f in files if f.get("empty_or_header_only")),
        "error_count": sum(1 for f in files if f.get("validation_status") == "error"),
        "files": files,
    }
    json_path = out_dir / "source_manifest.json"
    json_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    csv_fields = [
        "relative_path",
        "file_name",
        "source_system",
        "row_count",
        "column_count",
        "size_bytes",
        "empty_or_header_only",
        "validation_status",
        "year_coverage_pct",
        "entity_match_rate_pct",
        "duplicate_rate",
        "sha256",
    ]
    csv_path = out_dir / "source_manifest.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(files)
    return {"json": json_path, "csv": csv_path}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--dry-run", action="store_true", help="Scan + write manifest without further side-effects")
    args = parser.parse_args(argv)
    files = scan_repo(args.root)
    paths = write_canonical_manifest(args.root, files)
    print(
        json.dumps(
            {
                "file_count": len(files),
                "json_path": str(paths["json"].relative_to(args.root)),
                "csv_path": str(paths["csv"].relative_to(args.root)),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
