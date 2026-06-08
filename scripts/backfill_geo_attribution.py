"""Backfill geo attribution on registry outputs already on disk.

Walks every `expected_output` declared in `registries/source_registry.yaml`
that currently exists, applies :func:`apply_post_ingest`, and rewrites the
file atomically (`.tmp` → rename). Idempotent: a file already carrying
populated `geo_municipality_code` columns is left untouched on a row-by-row
basis by the underlying attributor.

Usage:
    python scripts/backfill_geo_attribution.py --root .
    python scripts/backfill_geo_attribution.py --root . --dry-run

Runbook posture: this script does NOT call upstream producers, fetch from
the network, or stage new inputs. It is enrichment-in-place on existing
files, so it does not violate the R4.9Z pause-lock rule prohibiting
download retries while `unfreeze_candidates == 0`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from contract_sweeper.runtime.geo_attribution import attribution_summary  # noqa: E402
from contract_sweeper.runtime.post_ingest import apply_post_ingest  # noqa: E402
from contract_sweeper.runtime.source_registry import all_sources  # noqa: E402


def _read(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path, dtype=str, low_memory=False)
    if suffix == ".parquet":
        return pd.read_parquet(path)
    raise ValueError(f"unsupported file extension: {path}")


def _write_atomic(df: pd.DataFrame, path: Path) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    suffix = path.suffix.lower()
    if suffix == ".csv":
        df.to_csv(tmp, index=False)
    elif suffix == ".parquet":
        df.to_parquet(tmp, index=False)
    else:
        raise ValueError(f"unsupported file extension: {path}")
    tmp.replace(path)


def _process_one(
    source_id: str,
    output_rel: str,
    *,
    root: Path,
    dry_run: bool,
) -> dict:
    abs_path = root / output_rel
    record: dict[str, object] = {
        "source_id": source_id,
        "output": output_rel,
        "status": "missing",
    }
    if not abs_path.exists():
        return record
    if abs_path.is_dir():
        # Some registry outputs point at a directory of operator-dropped files
        # rather than a single CSV. Backfill can't enrich a directory in place;
        # those land via per-source ingesters, not this script.
        record["status"] = "directory_skipped"
        return record
    if abs_path.suffix.lower() not in (".csv", ".parquet"):
        record["status"] = "unsupported_format"
        return record
    try:
        df = _read(abs_path)
    except Exception as exc:  # noqa: BLE001
        record["status"] = "read_error"
        record["error"] = str(exc)
        return record

    enriched = apply_post_ingest(df, source_id=source_id, root=root)
    summary = attribution_summary(enriched)
    record.update(
        {
            "status": "dry_run" if dry_run else "rewritten",
            "rows": summary["total"],
            "attributed": summary["attributed"],
            "unknown": summary["unknown"],
            "exact_fips": summary["exact_fips"],
            "exact_name": summary["exact_name"],
            "normalized_name": summary["normalized_name"],
            "fuzzy_name": summary["fuzzy_name"],
        }
    )
    if not dry_run:
        _write_atomic(enriched, abs_path)
    return record


def run(root: Path, *, dry_run: bool) -> dict:
    sources = all_sources(root)
    rewritten: list[dict] = []
    missing: list[dict] = []
    errors: list[dict] = []
    skipped: list[dict] = []
    for src in sources:
        sid = src.get("source_id", "")
        for out in src.get("expected_outputs", []) or []:
            rec = _process_one(sid, out, root=root, dry_run=dry_run)
            if rec["status"] == "missing":
                missing.append(rec)
            elif rec["status"] == "read_error":
                errors.append(rec)
            elif rec["status"] in ("directory_skipped", "unsupported_format"):
                skipped.append(rec)
            else:
                rewritten.append(rec)
    return {
        "root": str(root),
        "dry_run": dry_run,
        "source_count": len(sources),
        "outputs_present": len(rewritten),
        "outputs_missing": len(missing),
        "outputs_skipped": len(skipped),
        "outputs_errored": len(errors),
        "rewritten": rewritten,
        "skipped": skipped,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute attribution stats without rewriting files.",
    )
    args = parser.parse_args(argv)
    report = run(args.root, dry_run=args.dry_run)
    print(json.dumps(report, indent=2))
    return 0 if not report["outputs_errored"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
