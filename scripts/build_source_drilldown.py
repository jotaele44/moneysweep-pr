"""Build the source-provenance drilldown index (Gate ``dashboard``, item ``source_drilldown``).

For every top-form artifact, trace its lineage: which producer wrote it, from
which source inputs, against which schema(s), and how many rows it carries. The
index is derived automatically from the committed per-producer manifests in
``data/manifests/`` (every ``scripts/build_*`` producer drops one), so it stays
in sync with the producers and never needs hand-maintenance. One entry per
output artifact — "click an artifact, see where it came from".

Deterministic: the volatile ``generated_at`` field of each manifest is ignored,
and entries are sorted by artifact path.

Output: ``exports/reports/source_drilldown.json`` + ``data/manifests/source_drilldown.json``

Reuses the stdlib schema validator (no ``jsonschema`` dep).

CLI::

    python scripts/build_source_drilldown.py            # write the index + manifest
    python scripts/build_source_drilldown.py --check     # validate without writing
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

MANIFEST_DIR = "data/manifests"
OUT = "exports/reports/source_drilldown.json"
MANIFEST_OUT = "data/manifests/source_drilldown.json"
SCHEMA = "schemas/source_drilldown.schema.json"

# Manifests this producer writes itself — excluded to avoid self-reference.
SELF_OUTPUTS = {
    OUT,
    MANIFEST_OUT,
    "exports/reports/analyst_reports_manifest.json",
    "data/manifests/analyst_reports_manifest.json",
    "exports/dashboard/index.html",
    "data/manifests/dashboard_explorer.json",
}


def _load_schema(root: Path) -> dict[str, Any]:
    return json.loads((root / SCHEMA).read_text(encoding="utf-8"))


def _phase_label(producer_phase: str) -> str:
    return producer_phase.removeprefix("TOP_FORM_").lower()


def _top_form_manifests(root: Path) -> list[dict[str, Any]]:
    """Load the committed per-producer manifests written by scripts/build_* producers."""
    manifests: list[dict[str, Any]] = []
    for path in sorted((root / MANIFEST_DIR).glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, dict) and str(data.get("producer_script", "")).startswith(
            "scripts/build_"
        ):
            manifests.append(data)
    return manifests


def build_entries(root: Path | None = None) -> list[dict[str, Any]]:
    """Return one lineage entry per output artifact, sorted by artifact path."""
    root = root or REPO_ROOT
    entries: list[dict[str, Any]] = []
    for m in _top_form_manifests(root):
        outputs = m.get("outputs") or ([m["output"]] if m.get("output") else [])
        schemas = [m[k] for k in ("schema", "node_schema", "edge_schema") if m.get(k)]
        source_inputs = list(m.get("source_inputs") or [])
        row_count = m.get("row_count")
        for artifact in outputs:
            if artifact in SELF_OUTPUTS:
                continue
            entry: dict[str, Any] = {
                "artifact": artifact,
                "producer_script": m["producer_script"],
                "producer_phase": m.get("producer_phase", ""),
                "phase_label": _phase_label(m.get("producer_phase", "")),
                "schemas": schemas,
                "source_inputs": source_inputs,
            }
            if isinstance(row_count, int):
                entry["row_count"] = row_count
            entries.append(entry)
    entries.sort(key=lambda e: e["artifact"])
    return entries


def check(entries: list[dict[str, Any]], root: Path | None = None) -> list[str]:
    """Return a list of problems (empty == valid)."""
    root = root or REPO_ROOT
    problems: list[str] = []
    if not entries:
        problems.append("no source drilldown entries produced")
    artifacts = [e["artifact"] for e in entries]
    if len(set(artifacts)) != len(artifacts):
        problems.append("duplicate artifact entries present")
    schema = _load_schema(root)
    for i, entry in enumerate(entries, start=1):
        for msg in validate_row(entry, schema):
            problems.append(f"entry {i} ({entry.get('artifact')}): {msg}")
    return problems


def build(root: Path | None = None) -> dict[str, Any]:
    """Build, validate, and write the drilldown index + provenance manifest."""
    root = root or REPO_ROOT
    entries = build_entries(root)
    problems = check(entries, root)
    if problems:
        raise ValueError("source_drilldown check failed: " + "; ".join(problems))
    payload = {"sources": entries}
    out_path = root / OUT
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    manifest = {
        "producer_script": "scripts/build_source_drilldown.py",
        "producer_phase": "TOP_FORM_SOURCE_DRILLDOWN",
        "schema": SCHEMA,
        "source_inputs": [MANIFEST_DIR],
        "output": OUT,
        "row_count": len(entries),
        "phase_labels": sorted({e["phase_label"] for e in entries}),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = root / MANIFEST_OUT
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the source-provenance drilldown index.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--check", action="store_true", help="Validate without writing.")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if args.check:
        entries = build_entries(root)
        problems = check(entries, root)
        print(
            json.dumps(
                {"ok": not problems, "row_count": len(entries), "problems": problems}, indent=2
            )
        )
        return 0 if not problems else 1
    print(json.dumps(build(root), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
