"""Build the analyst-reports catalog (Gate ``dashboard``, item ``analyst_reports``).

A standardized table-of-contents for the analyst-facing deliverables produced by
the top-form layer — the reference registries, the influence / debt_fiscal
tables, the graph and GIS exports, and the FOIA program. Each entry carries a
human title, its gate, path, format, and producing script; the producer reads
the **live** row count from each artifact so the catalog reflects reality, and
marks ``status`` done/missing by file presence.

Output: ``exports/reports/analyst_reports_manifest.json``
        + ``data/manifests/analyst_reports_manifest.json``

Reuses ``name_hash`` and the stdlib schema validator (no ``jsonschema`` dep).

CLI::

    python scripts/build_analyst_reports_manifest.py            # write the catalog + manifest
    python scripts/build_analyst_reports_manifest.py --check     # validate without writing
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

from contract_sweeper.runtime.canonical_ids import name_hash
from contract_sweeper.validation.canonical_v1_schema import validate_row

REPO_ROOT = Path(__file__).resolve().parents[1]

OUT = "exports/reports/analyst_reports_manifest.json"
MANIFEST_OUT = "data/manifests/analyst_reports_manifest.json"
SCHEMA = "schemas/analyst_reports_manifest.schema.json"

# Curated catalog of the analyst-facing deliverables: (path, title, gate, format,
# producer_script). row_count + status are filled live by the producer.
CATALOG: list[tuple[str, str, str, str, str]] = [
    (
        "data/reference/entity_master.csv",
        "Entity Master",
        "entity_master",
        "csv",
        "scripts/build_entity_master.py",
    ),
    (
        "data/reference/agency_master.csv",
        "Agency & Municipio Master",
        "entity_master",
        "csv",
        "scripts/build_agency_master.py",
    ),
    (
        "data/reference/person_master.csv",
        "Person Master",
        "entity_master",
        "csv",
        "scripts/build_person_master.py",
    ),
    (
        "data/reference/entity_aliases.csv",
        "Entity Aliases",
        "entity_master",
        "csv",
        "scripts/build_entity_aliases.py",
    ),
    (
        "data/reference/entity_parent_map.csv",
        "Entity Parent / Operator Map",
        "entity_master",
        "csv",
        "scripts/build_entity_parent_map.py",
    ),
    (
        "reports/entity_resolution_review_queue.csv",
        "Entity Resolution Review Queue",
        "entity_master",
        "csv",
        "scripts/build_entity_resolution_review_queue.py",
    ),
    (
        "data/reference/influence_edges.csv",
        "Influence Edges",
        "influence",
        "csv",
        "scripts/build_influence_edges.py",
    ),
    (
        "data/reference/debt_instruments.csv",
        "Debt Instruments",
        "debt_fiscal",
        "csv",
        "scripts/build_debt_instruments.py",
    ),
    (
        "data/reference/creditor_mapping.csv",
        "Creditor Mapping",
        "debt_fiscal",
        "csv",
        "scripts/build_creditor_mapping.py",
    ),
    (
        "data/reference/fiscal_control_events.csv",
        "Fiscal Control Events Timeline",
        "debt_fiscal",
        "csv",
        "scripts/build_fiscal_control_events.py",
    ),
    (
        "data/reference/geo_reason_codes.csv",
        "Geo Resolution Codes",
        "gis",
        "csv",
        "scripts/build_geo_reason_codes.py",
    ),
    (
        "data/reference/hq_bias_correction.csv",
        "HQ Bias Correction Contract",
        "gis",
        "csv",
        "scripts/build_hq_bias_reference.py",
    ),
    (
        "exports/gis/layer_manifest.json",
        "GIS Layer Manifest",
        "gis",
        "json",
        "scripts/build_gis_layer_manifest.py",
    ),
    (
        "exports/graph/nodes.csv",
        "Graph Nodes",
        "graph_export",
        "csv",
        "scripts/build_graph_export.py",
    ),
    (
        "exports/graph/edges.csv",
        "Graph Edges",
        "graph_export",
        "csv",
        "scripts/build_graph_export.py",
    ),
    (
        "reports/foia_priority_queue.csv",
        "FOIA Priority Queue",
        "foia",
        "csv",
        "scripts/build_foia_tracker.py",
    ),
    (
        "reports/foia_yield_tracking.csv",
        "FOIA Yield Tracking",
        "foia",
        "csv",
        "scripts/build_foia_yield_tracking.py",
    ),
    (
        "docs/foia_letters/FOIA_c509296376f145b1.md",
        "FOIA Letter — HUD DRGR",
        "foia",
        "md",
        "scripts/build_foia_letters.py",
    ),
    (
        "docs/foia_letters/FOIA_3429122f5837fd47.md",
        "FOIA Letter — PRASA",
        "foia",
        "md",
        "scripts/build_foia_letters.py",
    ),
    (
        "docs/foia_letters/FOIA_aef916ac9b8ed071.md",
        "FOIA Letter — OCPR",
        "foia",
        "md",
        "scripts/build_foia_letters.py",
    ),
    (
        "docs/foia_letters/FOIA_f7d5acaf207ff8a5.md",
        "FOIA Letter — COR3",
        "foia",
        "md",
        "scripts/build_foia_letters.py",
    ),
    (
        "docs/foia_letters/FOIA_64d22dfe3108f7b1.md",
        "FOIA Letter — GSA FSRS",
        "foia",
        "md",
        "scripts/build_foia_letters.py",
    ),
    (
        "docs/foia_letters/FOIA_95021847de4153af.md",
        "FOIA Letter — SAM.gov",
        "foia",
        "md",
        "scripts/build_foia_letters.py",
    ),
    (
        "docs/foia_letters/FOIA_7ef254a89545013c.md",
        "FOIA Letter — OEG (Cabilderos)",
        "foia",
        "md",
        "scripts/build_foia_letters.py",
    ),
    (
        "docs/foia_letters/FOIA_220df26653119d96.md",
        "FOIA Letter — CEE (Donaciones)",
        "foia",
        "md",
        "scripts/build_foia_letters.py",
    ),
    (
        "docs/foia_letters/FOIA_7fef81739082ae00.md",
        "FOIA Letter — compras.pr.gov",
        "foia",
        "md",
        "scripts/build_foia_letters.py",
    ),
]


def _load_schema(root: Path) -> dict[str, Any]:
    return json.loads((root / SCHEMA).read_text(encoding="utf-8"))


def _row_count(path: Path, fmt: str) -> int:
    """Live record count: CSV data rows, JSON array/layers length."""
    if not path.exists():
        return 0
    if fmt == "csv":
        with path.open(newline="", encoding="utf-8") as fh:
            return max(0, sum(1 for _ in csv.reader(fh)) - 1)
    if fmt == "json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return len(data)
        if isinstance(data, dict):
            for key in ("layers", "sources", "reports", "rows"):
                if isinstance(data.get(key), list):
                    return len(data[key])
        return 0
    return 0


def build_rows(root: Path | None = None) -> list[dict[str, Any]]:
    """Return the analyst-report catalog entries with live row counts."""
    root = root or REPO_ROOT
    rows: list[dict[str, Any]] = []
    for path, title, gate, fmt, producer in CATALOG:
        p = root / path
        rows.append(
            {
                "report_id": f"RPT_{name_hash(path)}",
                "title": title,
                "gate": gate,
                "path": path,
                "format": fmt,
                "producer_script": producer,
                "status": "done" if p.exists() else "missing",
                "row_count": _row_count(p, fmt),
            }
        )
    return rows


def check(rows: list[dict[str, Any]], root: Path | None = None) -> list[str]:
    """Return a list of problems (empty == valid)."""
    root = root or REPO_ROOT
    problems: list[str] = []
    if not rows:
        problems.append("no analyst reports catalogued")
    ids = [r["report_id"] for r in rows]
    if len(set(ids)) != len(ids):
        problems.append("duplicate report_id values present")
    schema = _load_schema(root)
    for i, row in enumerate(rows, start=1):
        for msg in validate_row(row, schema):
            problems.append(f"entry {i} ({row.get('path')}): {msg}")
        if row["status"] != "done":
            problems.append(f"entry {i}: catalogued report {row['path']} is missing on disk")
    return problems


def build(root: Path | None = None) -> dict[str, Any]:
    """Build, validate, and write the analyst-reports catalog + manifest."""
    root = root or REPO_ROOT
    rows = build_rows(root)
    problems = check(rows, root)
    if problems:
        raise ValueError("analyst_reports_manifest check failed: " + "; ".join(problems))
    payload = {"reports": rows}
    out_path = root / OUT
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    manifest = {
        "producer_script": "scripts/build_analyst_reports_manifest.py",
        "producer_phase": "TOP_FORM_ANALYST_REPORTS",
        "schema": SCHEMA,
        "source_inputs": [p for p, *_ in CATALOG],
        "output": OUT,
        "row_count": len(rows),
        "gates": sorted({r["gate"] for r in rows}),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = root / MANIFEST_OUT
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the analyst-reports catalog.")
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
