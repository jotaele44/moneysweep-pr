"""Build a committed row-count manifest for the gitignored staging masters.

The materialized masters under ``data/staging/processed/*.csv`` are gitignored
(too large to commit — ``pr_grants_master.csv`` alone is ~143 MB, and the
``size-guard`` gate caps tracked files at 5 MiB). That means a clean CI checkout
sees zero rows and the committed coverage reports read 0%, even though the data
exists locally.

This manifest records ``{row_count, sha256, size_bytes, generated_at}`` per
processed CSV under ``data/manifests/staging_masters.json`` (which IS tracked).
``gap_analysis_builder._file_status`` falls back to this manifest when a declared
output is absent, so committed reports reflect real coverage without committing
the bulk data. Regenerate after a local data refresh:

    python3 scripts/build_staging_manifest.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = PROJECT_ROOT / "data" / "staging" / "processed"
MANIFEST_PATH = PROJECT_ROOT / "data" / "manifests" / "staging_masters.json"


def _csv_row_count(path: Path) -> int:
    """Data rows (excluding the header); -1 if unreadable."""
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            return max(0, sum(1 for _ in f) - 1)
    except OSError:
        return -1


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(root: Path = PROJECT_ROOT) -> dict:
    processed = root / "data" / "staging" / "processed"
    files: dict[str, dict] = {}
    for p in sorted(processed.glob("*.csv")):
        rel = p.relative_to(root).as_posix()
        files[rel] = {
            "row_count": _csv_row_count(p),
            "sha256": _sha256(p),
            "size_bytes": p.stat().st_size,
        }
    return {
        "schema_version": "staging_masters_v1",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": (
            "Row counts for the gitignored data/staging/processed masters. "
            "Committed source of truth for coverage reports in a clean checkout "
            "(the CSVs themselves are too large to track — see size-guard). "
            "Regenerate with scripts/build_staging_manifest.py after a data refresh."
        ),
        "files": files,
    }


def main() -> int:
    manifest = build_manifest(PROJECT_ROOT)
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    n = len(manifest["files"])
    total = sum(v["row_count"] for v in manifest["files"].values() if v["row_count"] > 0)
    print(f"wrote {MANIFEST_PATH.relative_to(PROJECT_ROOT)} — {n} files, {total:,} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
