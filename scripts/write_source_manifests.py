"""Write per-source manifests for registry-declared sources.

For each source_id, reads its expected_outputs from source_registry.yaml,
profiles every present file via manifest_runtime, and writes:
  data/manifests/<source_id>/<utc_timestamp>.json

Also refreshes the canonical data/manifests/source_manifest.json + .csv.

Usage:
  python3 scripts/write_source_manifests.py
  python3 scripts/write_source_manifests.py --sources usaspending_prime,fec,lda
  python3 scripts/write_source_manifests.py --required-only
  python3 scripts/write_source_manifests.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.runtime.manifest_runtime import (
    profile_file,
    scan_repo,
    write_canonical_manifest,
    write_per_source_manifest,
)
from contract_sweeper.runtime.source_registry import (
    REPO_ROOT,
    all_sources,
    expected_outputs_for,
    required_sources,
    source_by_id,
)


def _profile_source(root: Path, src: dict) -> list[dict]:
    paths = expected_outputs_for(src, root)
    items = []
    for p in paths:
        if not p.exists():
            continue
        try:
            items.append(
                profile_file(
                    p,
                    root=root,
                    source_id=src["source_id"],
                    source_url=src.get("endpoint_url"),
                    schema_version=src.get("schema_version"),
                )
            )
        except Exception as exc:
            items.append({
                "relative_path": p.relative_to(root).as_posix(),
                "source_system": src["source_id"],
                "validation_status": "error",
                "error": str(exc),
            })
    return items


def run(
    root: Path,
    *,
    source_ids: list[str] | None = None,
    required_only: bool = False,
    dry_run: bool = False,
) -> dict:
    if source_ids:
        sources = [s for s in all_sources(root) if s["source_id"] in source_ids]
    elif required_only:
        sources = required_sources(root)
    else:
        sources = all_sources(root)

    results = {}
    for src in sources:
        sid = src["source_id"]
        items = _profile_source(root, src)
        if not items:
            results[sid] = {"file_count": 0, "manifest_path": None}
            continue
        if not dry_run:
            out_path = write_per_source_manifest(root, source_id=sid, files=items)
            results[sid] = {
                "file_count": len(items),
                "manifest_path": str(out_path.relative_to(root)),
            }
        else:
            results[sid] = {"file_count": len(items), "manifest_path": "(dry-run)"}

    if not dry_run:
        all_files = scan_repo(root)
        canon_paths = write_canonical_manifest(root, all_files)
        results["_canonical"] = {
            "json": str(canon_paths["json"].relative_to(root)),
            "csv": str(canon_paths["csv"].relative_to(root)),
            "total_files": len(all_files),
        }

    return results


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=REPO_ROOT)
    p.add_argument("--sources", help="Comma-separated list of source_ids")
    p.add_argument("--required-only", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)

    source_ids = [s.strip() for s in a.sources.split(",")] if a.sources else None
    results = run(
        Path(a.root),
        source_ids=source_ids,
        required_only=a.required_only,
        dry_run=a.dry_run,
    )
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
