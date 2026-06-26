"""Lock the 78-municipio PR crosswalk (Gate ``gis``, item ``municipality_crosswalk``).

The crosswalk ``data/reference/pr_78_municipio_crosswalk.csv`` is the committed
spatial key that every GIS layer and the geo-reasoning resolver join against.
This producer locks it: it validates every row against
``schemas/municipality_crosswalk.schema.json`` and enforces the crosswalk
invariants (exactly 78 municipios, unique ``72xxx`` FIPS geoids, geoid==code),
then writes a provenance manifest. The crosswalk file itself is the authority,
so this is a lock-in-place validator — it does not rewrite the CSV.

Reuses the stdlib schema validator (no ``jsonschema`` dep).

CLI::

    python scripts/build_municipality_crosswalk.py            # validate + write manifest
    python scripts/build_municipality_crosswalk.py --check     # validate only
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

from moneysweep.validation.canonical_v1_schema import validate_row

REPO_ROOT = Path(__file__).resolve().parents[1]

CROSSWALK = "data/reference/pr_78_municipio_crosswalk.csv"
MANIFEST_OUT = "data/manifests/municipality_crosswalk.json"
SCHEMA = "schemas/municipality_crosswalk.schema.json"
EXPECTED_COUNT = 78


def _load_schema(root: Path) -> dict[str, Any]:
    return json.loads((root / SCHEMA).read_text(encoding="utf-8"))


def build_rows(root: Path | None = None) -> list[dict[str, Any]]:
    """Return the committed crosswalk rows (the file is the authority)."""
    root = root or REPO_ROOT
    with (root / CROSSWALK).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def check(rows: list[dict[str, Any]], root: Path | None = None) -> list[str]:
    """Return a list of problems (empty == valid)."""
    root = root or REPO_ROOT
    problems: list[str] = []
    if len(rows) != EXPECTED_COUNT:
        problems.append(f"expected {EXPECTED_COUNT} municipios, got {len(rows)}")
    geoids = [r["municipality_geoid"] for r in rows]
    if len(set(geoids)) != len(geoids):
        problems.append("duplicate municipality_geoid values present")
    schema = _load_schema(root)
    for i, row in enumerate(rows, start=1):
        for msg in validate_row(row, schema):
            problems.append(f"row {i} ({row.get('municipality_geoid')}): {msg}")
        if row["municipality_geoid"] != row["municipality_code"]:
            problems.append(
                f"row {i}: geoid {row['municipality_geoid']} != code {row['municipality_code']}"
            )
    return problems


def build(root: Path | None = None) -> dict[str, Any]:
    """Validate the crosswalk and write a provenance manifest."""
    root = root or REPO_ROOT
    rows = build_rows(root)
    problems = check(rows, root)
    if problems:
        raise ValueError("municipality_crosswalk check failed: " + "; ".join(problems))
    manifest = {
        "producer_script": "scripts/build_municipality_crosswalk.py",
        "producer_phase": "TOP_FORM_MUNICIPALITY_CROSSWALK",
        "schema": SCHEMA,
        "source_inputs": [CROSSWALK],
        "output": CROSSWALK,
        "row_count": len(rows),
        "geoid_range": [
            min(r["municipality_geoid"] for r in rows),
            max(r["municipality_geoid"] for r in rows),
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = root / MANIFEST_OUT
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lock the 78-municipio PR crosswalk.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--check", action="store_true", help="Validate without writing.")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if args.check:
        rows = build_rows(root)
        problems = check(rows, root)
        print(
            json.dumps({"ok": not problems, "row_count": len(rows), "problems": problems}, indent=2)
        )
        return 0 if not problems else 1
    print(json.dumps(build(root), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
