"""Build the GIS layer manifest (Gate ``gis``, item ``layer_manifest``).

Catalogues the spatial layers of the project against
``schemas/gis_layer_manifest.schema.json``: which layers are materialized today
(the municipio crosswalk key, the influence and debt overlays that join on it)
and which are blocked pending geometry/coordinates (project points,
infrastructure assets, contract flows). Each layer carries an honest ``status``
from the top-form vocabulary.

Output: ``exports/gis/layer_manifest.json`` + ``data/manifests/gis_layer_manifest.json``

Reuses the stdlib schema validator (no ``jsonschema`` dep).

CLI::

    python scripts/build_gis_layer_manifest.py            # write the manifest
    python scripts/build_gis_layer_manifest.py --check     # validate without writing
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_sweeper.validation.canonical_v1_schema import validate_row

REPO_ROOT = Path(__file__).resolve().parents[1]

OUT = "exports/gis/layer_manifest.json"
MANIFEST_OUT = "data/manifests/gis_layer_manifest.json"
SCHEMA = "schemas/gis_layer_manifest.schema.json"

# Each layer's status reflects what is materialized in-repo today. Layers needing
# real coordinates/geometry (no lat/lon committed) are honestly marked blocked.
LAYERS: list[dict[str, Any]] = [
    {
        "layer_id": "municipality_density",
        "layer_name": "PR Municipio Density Key",
        "layer_type": "municipality_density",
        "path": "data/reference/pr_78_municipio_crosswalk.csv",
        "geometry_type": "None",
        "source_id": "pr_78_municipio_crosswalk",
        "refresh_frequency": "annual",
        "status": "done",
        "notes": "Locked 78-municipio crosswalk; the spatial key every layer joins on.",
    },
    {
        "layer_id": "influence_overlay",
        "layer_name": "Influence Edge Overlay",
        "layer_type": "influence_overlay",
        "path": "data/reference/influence_edges.csv",
        "geometry_type": "None",
        "source_id": "influence_edges",
        "refresh_frequency": "on_change",
        "status": "done",
        "notes": "Influence edges joinable to municipio via entity location.",
    },
    {
        "layer_id": "debt_fiscal_overlay",
        "layer_name": "Debt / Creditor Overlay",
        "layer_type": "debt_fiscal_overlay",
        "path": "data/reference/creditor_mapping.csv",
        "geometry_type": "None",
        "source_id": "creditor_mapping",
        "refresh_frequency": "on_change",
        "status": "partial",
        "notes": "Issuer-level creditor registry; per-municipio attribution pending.",
    },
    {
        "layer_id": "project_points",
        "layer_name": "Project Point Layer",
        "layer_type": "project_points",
        "path": "exports/gis/project_points.geojson",
        "geometry_type": "Point",
        "source_id": "pr_infrastructure_projects",
        "refresh_frequency": "on_change",
        "status": "blocked",
        "notes": "No lat/lon committed; geocoding needs egress to a geocoder.",
    },
    {
        "layer_id": "infrastructure_assets",
        "layer_name": "Infrastructure Asset Layer",
        "layer_type": "infrastructure_assets",
        "path": "exports/gis/infrastructure_assets.geojson",
        "geometry_type": "Point",
        "source_id": "pr_properties",
        "refresh_frequency": "on_change",
        "status": "blocked",
        "notes": "No asset coordinates committed.",
    },
    {
        "layer_id": "contract_flows",
        "layer_name": "Contract Flow Layer",
        "layer_type": "contract_flows",
        "path": "exports/gis/contract_flows.geojson",
        "geometry_type": "LineString",
        "source_id": "pr_public_contracts",
        "refresh_frequency": "on_change",
        "status": "blocked",
        "notes": "Origin/destination geometry needs project + recipient coordinates.",
    },
]


def _load_schema(root: Path) -> dict[str, Any]:
    return json.loads((root / SCHEMA).read_text(encoding="utf-8"))


def build_manifest(root: Path | None = None) -> dict[str, Any]:
    """Return the layer-manifest payload."""
    return {"layers": [dict(layer) for layer in LAYERS]}


def check(manifest: dict[str, Any], root: Path | None = None) -> list[str]:
    """Return a list of problems (empty == valid)."""
    root = root or REPO_ROOT
    problems: list[str] = []
    layers = manifest.get("layers", [])
    if not layers:
        problems.append("no GIS layers in manifest")
    ids = [layer["layer_id"] for layer in layers]
    if len(set(ids)) != len(ids):
        problems.append("duplicate layer_id values present")

    schema = _load_schema(root)
    item_schema = schema["properties"]["layers"]["items"]
    for i, layer in enumerate(layers, start=1):
        for msg in validate_row(layer, item_schema):
            problems.append(f"layer {i} ({layer.get('layer_id')}): {msg}")
    return problems


def build(root: Path | None = None) -> dict[str, Any]:
    """Build, validate, and write the GIS layer manifest + provenance manifest."""
    root = root or REPO_ROOT
    manifest = build_manifest(root)
    problems = check(manifest, root)
    if problems:
        raise ValueError("gis_layer_manifest check failed: " + "; ".join(problems))
    out_path = root / OUT
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    provenance = {
        "producer_script": "scripts/build_gis_layer_manifest.py",
        "producer_phase": "TOP_FORM_GIS_LAYER_MANIFEST",
        "schema": SCHEMA,
        "output": OUT,
        "layer_count": len(manifest["layers"]),
        "status_breakdown": {
            s: sum(1 for layer in manifest["layers"] if layer["status"] == s)
            for s in sorted({layer["status"] for layer in manifest["layers"]})
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    prov_path = root / MANIFEST_OUT
    prov_path.parent.mkdir(parents=True, exist_ok=True)
    prov_path.write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    return provenance


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the GIS layer manifest.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--check", action="store_true", help="Validate without writing.")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if args.check:
        manifest = build_manifest(root)
        problems = check(manifest, root)
        print(json.dumps({"ok": not problems, "layer_count": len(manifest["layers"]), "problems": problems}, indent=2))
        return 0 if not problems else 1
    print(json.dumps(build(root), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
