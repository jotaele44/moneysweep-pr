"""Lock the geo-resolution controlled vocabulary (Gate ``gis``, item ``geo_reason_codes``).

The geo-reasoning resolver (``scripts/run_contract_finance_geo_reasoning.py``)
classifies every contract/finance row with a ``geo_resolution_reason`` (how the
location was determined) and a ``jurisdiction_class`` (the resulting bucket).
This producer imports those tuples directly from the resolver and emits a
schema-locked reference table with a curated description for each code, so the
vocabulary cannot drift from the implementation without breaking ``check()``.

Output: ``data/reference/geo_reason_codes.csv`` + ``data/manifests/geo_reason_codes.json``

Reuses the stdlib schema validator (no ``jsonschema`` dep).

CLI::

    python scripts/build_geo_reason_codes.py            # write the CSV + manifest
    python scripts/build_geo_reason_codes.py --check     # validate without writing
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
    UNKNOWN_REASONS,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

OUT = "data/reference/geo_reason_codes.csv"
MANIFEST_OUT = "data/manifests/geo_reason_codes.json"
SCHEMA = "schemas/geo_reason_codes.schema.json"

COLUMNS = ["code", "kind", "is_unknown", "description"]

REASON_DESCRIPTIONS = {
    "place_of_performance_exact": "Location taken from an exact place-of-performance municipio code.",
    "project_municipality_match": "Location matched from the project's municipality.",
    "recipient_municipality_match": "Location matched from the recipient's municipality.",
    "municipality_name_only": "Location resolved from a municipality name string only (no code).",
    "headquarters_only": "Only a headquarters location was available — flagged as HQ bias, not place of performance.",
    "agency_default": "No row-level location; fell back to the awarding agency's default.",
    "outside_pr": "Location resolved to a place outside Puerto Rico.",
    "missing_location": "No usable location evidence present in the row.",
    "ambiguous_location": "Multiple conflicting locations could not be disambiguated.",
    "invalid_pr_municipio": "A PR municipio code/name was present but did not validate against the crosswalk.",
    "parser_failed": "The location parser failed to interpret the raw value.",
}

JURISDICTION_DESCRIPTIONS = {
    "PR_MUNICIPIO": "Resolved to one of the 78 Puerto Rico municipios.",
    "UNKNOWN_MISSING": "No location evidence — jurisdiction unknown.",
    "UNKNOWN_AMBIGUOUS": "Conflicting location evidence — jurisdiction unknown.",
    "OUTSIDE_PR_US_STATE": "Resolved to a U.S. state outside Puerto Rico.",
    "OUTSIDE_PR_US_COUNTY": "Resolved to a U.S. county outside Puerto Rico.",
    "OUTSIDE_PR_FOREIGN": "Resolved to a foreign country.",
    "HEADQUARTERS_ONLY": "Only a headquarters location was available (HQ-bias bucket).",
    "AGENCY_DEFAULT": "Fell back to the awarding agency's default jurisdiction.",
}


def _load_schema(root: Path) -> dict[str, Any]:
    return json.loads((root / SCHEMA).read_text(encoding="utf-8"))


def build_rows(root: Path | None = None) -> list[dict[str, Any]]:
    """Return one row per resolver code (reasons then jurisdiction classes)."""
    rows: list[dict[str, Any]] = []
    for code in GEO_RESOLUTION_REASONS:
        rows.append({
            "code": code,
            "kind": "geo_resolution_reason",
            "is_unknown": "true" if code in UNKNOWN_REASONS else "false",
            "description": REASON_DESCRIPTIONS.get(code, ""),
        })
    for code in JURISDICTION_CLASSES:
        rows.append({
            "code": code,
            "kind": "jurisdiction_class",
            "is_unknown": "true" if code in UNKNOWN_JURISDICTIONS else "false",
            "description": JURISDICTION_DESCRIPTIONS.get(code, ""),
        })
    return rows


def check(rows: list[dict[str, Any]], root: Path | None = None) -> list[str]:
    """Return a list of problems (empty == valid)."""
    root = root or REPO_ROOT
    problems: list[str] = []
    if not rows:
        problems.append("no geo reason codes produced")

    # Every resolver code must appear exactly once with a description.
    reasons = {r["code"] for r in rows if r["kind"] == "geo_resolution_reason"}
    jclasses = {r["code"] for r in rows if r["kind"] == "jurisdiction_class"}
    if reasons != set(GEO_RESOLUTION_REASONS):
        problems.append("geo_resolution_reason set drifted from the resolver")
    if jclasses != set(JURISDICTION_CLASSES):
        problems.append("jurisdiction_class set drifted from the resolver")

    schema = _load_schema(root)
    for i, row in enumerate(rows, start=1):
        for msg in validate_row(row, schema):
            problems.append(f"row {i} ({row.get('code')}): {msg}")
    return problems


def _write(rows: list[dict[str, Any]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build(root: Path | None = None) -> dict[str, Any]:
    """Build, validate, and write the geo-reason-codes CSV + manifest."""
    root = root or REPO_ROOT
    rows = build_rows(root)
    problems = check(rows, root)
    if problems:
        raise ValueError("geo_reason_codes check failed: " + "; ".join(problems))
    _write(rows, root / OUT)
    manifest = {
        "producer_script": "scripts/build_geo_reason_codes.py",
        "producer_phase": "TOP_FORM_GEO_REASON_CODES",
        "schema": SCHEMA,
        "source_inputs": ["scripts/run_contract_finance_geo_reasoning.py"],
        "output": OUT,
        "row_count": len(rows),
        "reason_count": len(GEO_RESOLUTION_REASONS),
        "jurisdiction_class_count": len(JURISDICTION_CLASSES),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = root / MANIFEST_OUT
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lock the geo-resolution controlled vocabulary.")
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
