"""Materialize the registered federal-contract source plane for MoneySweep.

This producer owns only ``pr_contracts_master.csv``.  The cross-source
``pr_all_awards_master.csv`` is deliberately excluded: it is a derived product
built by ``scripts/build_unified_master.py`` and must carry separate lineage.

The materializer refreshes the FPDS/USAspending expansion inputs that are
available automatically, normalizes the expansion universe, and rebuilds the
contracts master. Historical/manual FPDS windows may be retained from the
operator workspace; a missing required input remains a hard failure in the
normalization/deduplication stages rather than being silently synthesized.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from scripts import auto_download, deduplicate_master, normalize_expansion_inputs
from scripts.config import PROJECT_ROOT

OUTPUT = "data/staging/processed/pr_contracts_master.csv"
MANIFEST = "data/manifests/usaspending_prime/materialization.json"


def _status_counts(results: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in results:
        status = str(result.get("status") or "UNKNOWN")
        counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def _hard_download_failures(results: list[dict[str, Any]]) -> list[str]:
    return sorted(
        str(result.get("filename") or "")
        for result in results
        if str(result.get("status") or "") in {"FAILED", "EMPTY"}
    )


def run(root: Path | None = None, *, force: bool = False) -> dict[str, Any]:
    root = Path(root) if root is not None else PROJECT_ROOT
    started_at = datetime.now(timezone.utc).isoformat()

    fpds = auto_download.download_all(root, force=force, only="fpds")
    usaspending = auto_download.download_all(root, force=force, only="usaspending")
    failures = _hard_download_failures(fpds) + _hard_download_failures(usaspending)
    if failures:
        raise RuntimeError("USAspending/FPDS acquisition failed: " + ", ".join(failures))

    normalize_result = normalize_expansion_inputs.main(root=root)
    dedupe_result = deduplicate_master.run(root=root)

    output = root / OUTPUT
    if not output.is_file():
        raise RuntimeError(f"contracts master was not produced: {OUTPUT}")
    frame = pd.read_csv(output, dtype=str, low_memory=False)
    if frame.empty:
        raise RuntimeError("contracts master is empty")

    manifest = {
        "schema_version": "moneysweep.usaspending_prime_materialization/v1",
        "source_id": "usaspending_prime",
        "producer": "scripts/materialize_usaspending_prime.py",
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "force": force,
        "acquisition": {
            "fpds": {
                "results": fpds,
                "status_counts": _status_counts(fpds),
            },
            "usaspending": {
                "results": usaspending,
                "status_counts": _status_counts(usaspending),
            },
        },
        "normalization_result": normalize_result,
        "deduplication_result": dedupe_result,
        "output": OUTPUT,
        "rows": len(frame),
        "derived_all_awards_excluded": True,
    }
    manifest_path = root / MANIFEST
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = run(args.root, force=args.force)
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
