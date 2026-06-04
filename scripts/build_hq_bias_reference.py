"""Lock the HQ-bias correction contract (Gate ``gis``, item ``hq_bias_correction``).

Headquarters-only locations must not be mistaken for place of performance — a
contract whose only location is the recipient's HQ would otherwise over-count
San Juan and other HQ municipios. The geo-reasoning resolver already implements
this correction: it emits the ``hq_bias_flag`` column, the ``headquarters_only``
reason, and the ``HEADQUARTERS_ONLY`` (unknown) jurisdiction bucket, and it
always prefers a real place-of-performance over an HQ location.

This producer locks that contract into a schema-validated reference table,
validating each referenced code against the resolver's own vocabulary so the
documentation cannot drift from the implementation.

Output: ``data/reference/hq_bias_correction.csv`` + ``data/manifests/hq_bias_correction.json``

Reuses the stdlib schema validator (no ``jsonschema`` dep).

CLI::

    python scripts/build_hq_bias_reference.py            # write the CSV + manifest
    python scripts/build_hq_bias_reference.py --check     # validate without writing
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.validation.canonical_v1_schema import validate_row
from scripts.run_contract_finance_geo_reasoning import (
    GEO_RESOLUTION_REASONS,
    JURISDICTION_CLASSES,
    UNKNOWN_JURISDICTIONS,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

OUT = "data/reference/hq_bias_correction.csv"
MANIFEST_OUT = "data/manifests/hq_bias_correction.json"
SCHEMA = "schemas/hq_bias_correction.schema.json"

# The place-of-performance precedence: real location reasons override HQ.
PLACE_PRECEDENCE = (
    "place_of_performance_exact>project_municipality_match>"
    "recipient_municipality_match>municipality_name_only>headquarters_only"
)

COLUMNS = ["aspect", "value", "description"]

ROWS: list[dict[str, Any]] = [
    {
        "aspect": "flag_column",
        "value": "hq_bias_flag",
        "description": "Boolean row column set true when the location came only from a headquarters, not a place of performance.",
    },
    {
        "aspect": "reason_code",
        "value": "headquarters_only",
        "description": "geo_resolution_reason emitted when only an HQ location was available.",
    },
    {
        "aspect": "jurisdiction_class",
        "value": "HEADQUARTERS_ONLY",
        "description": "Jurisdiction bucket for HQ-only rows; treated as unknown jurisdiction, not as a municipio of performance.",
    },
    {
        "aspect": "place_precedence",
        "value": PLACE_PRECEDENCE,
        "description": "Resolution precedence: a real place-of-performance/project/recipient municipio always overrides a headquarters location.",
    },
]


def _load_schema(root: Path) -> dict[str, Any]:
    return json.loads((root / SCHEMA).read_text(encoding="utf-8"))


def build_rows(root: Path | None = None) -> list[dict[str, Any]]:
    """Return the HQ-bias correction contract rows."""
    return [dict(r) for r in ROWS]


def check(rows: list[dict[str, Any]], root: Path | None = None) -> list[str]:
    """Return a list of problems (empty == valid)."""
    root = root or REPO_ROOT
    problems: list[str] = []
    if not rows:
        problems.append("no hq_bias_correction rows produced")

    # Lock each referenced code against the resolver's vocabulary.
    by_aspect = {r["aspect"]: r["value"] for r in rows}
    if by_aspect.get("reason_code") not in GEO_RESOLUTION_REASONS:
        problems.append("reason_code drifted from resolver GEO_RESOLUTION_REASONS")
    jclass = by_aspect.get("jurisdiction_class")
    if jclass not in JURISDICTION_CLASSES:
        problems.append("jurisdiction_class drifted from resolver JURISDICTION_CLASSES")
    if jclass not in UNKNOWN_JURISDICTIONS:
        problems.append("HEADQUARTERS_ONLY must be an unknown jurisdiction (not a place of performance)")
    for code in by_aspect.get("place_precedence", "").split(">"):
        if code and code not in GEO_RESOLUTION_REASONS:
            problems.append(f"place_precedence references unknown reason {code!r}")

    schema = _load_schema(root)
    for i, row in enumerate(rows, start=1):
        for msg in validate_row(row, schema):
            problems.append(f"row {i} ({row.get('aspect')}): {msg}")
    return problems


def _write(rows: list[dict[str, Any]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build(root: Path | None = None) -> dict[str, Any]:
    """Build, validate, and write the HQ-bias correction CSV + manifest."""
    root = root or REPO_ROOT
    rows = build_rows(root)
    problems = check(rows, root)
    if problems:
        raise ValueError("hq_bias_correction check failed: " + "; ".join(problems))
    _write(rows, root / OUT)
    manifest = {
        "producer_script": "scripts/build_hq_bias_reference.py",
        "producer_phase": "TOP_FORM_HQ_BIAS_CORRECTION",
        "schema": SCHEMA,
        "source_inputs": ["scripts/run_contract_finance_geo_reasoning.py"],
        "output": OUT,
        "row_count": len(rows),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = root / MANIFEST_OUT
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lock the HQ-bias correction contract.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--check", action="store_true", help="Validate without writing.")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if args.check:
        rows = build_rows(root)
        problems = check(rows, root)
        print(json.dumps({"ok": not problems, "row_count": len(rows), "problems": problems}, indent=2))
        return 0 if not problems else 1
    print(json.dumps(build(root), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
