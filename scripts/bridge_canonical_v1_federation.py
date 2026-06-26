"""Write canonical_v1 -> federation JSONL streams + manifest (WS-Q).

Runs the bridge mapper (``moneysweep.federation.canonical_v1_bridge``) and
writes ``sources.jsonl``, ``entities.jsonl``, ``relationships.jsonl`` under
``data/exports/canonical_v1_federation/`` plus a coverage manifest. Each row is
structurally validated against the required-field set of the matching federation
schema (stdlib; no jsonschema dependency).

The sources stream is composed of the canonical_v1 evidence sources PLUS the
standalone federal-publications feed (``merge_external_sources`` — unreferenced
evidence sources; entities/relationships and edges_federated_pct are unchanged).
The manifest's ``source_feeds`` records the split.

CLI::

    python scripts/bridge_canonical_v1_federation.py --root .
    python scripts/bridge_canonical_v1_federation.py --check     # validate, no write
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moneysweep.federation.canonical_v1_bridge import build_streams

OUT_DIR = "data/exports/canonical_v1_federation"
SCHEMA_DIR = "schemas"

# stream -> (schema filename, output filename)
STREAMS = {
    "sources": ("moneysweep_source.schema.json", "sources.jsonl"),
    "entities": ("moneysweep_entity.schema.json", "entities.jsonl"),
    "relationships": ("moneysweep_relationship.schema.json", "relationships.jsonl"),
}

# Standalone federal-publications source feed composed into the sources stream.
# These are real, already-conformant federation `sources` rows (built by
# scripts/ingest_federal_publications.py); they are UNREFERENCED — they carry no
# entities or edges — so entities/relationships and edges_federated_pct are
# unchanged. They reach the Hub aggregate as sources, filterable by
# lineage.producer_phase == FEDERAL_PUBLICATIONS_PHASE.
FEDERAL_PUBLICATIONS = "data/sources/federal_publications.jsonl"
FEDERAL_PUBLICATIONS_PHASE = "FEDERAL_PUBLICATIONS_INGEST"


def merge_external_sources(streams: dict[str, Any], root: Path) -> int:
    """Compose the federal-publications feed into ``streams["sources"]``.

    Reads ``FEDERAL_PUBLICATIONS`` (already-conformant federation source rows),
    dedups by ``source_id`` against the canonical_v1 sources, appends the rest in
    deterministic ``source_id`` order, and returns the number added. Only the
    sources stream is touched — entities/relationships are left intact.
    """
    path = root / FEDERAL_PUBLICATIONS
    if not path.is_file():
        return 0
    seen = {s["source_id"] for s in streams["sources"]}
    pubs: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        sid = row.get("source_id")
        if not sid or sid in seen:
            continue
        seen.add(sid)
        pubs.append(row)
    pubs.sort(key=lambda r: r["source_id"])
    streams["sources"].extend(pubs)
    return len(pubs)


def _required(schema_file: str, root: Path) -> set[str]:
    data = json.loads((root / SCHEMA_DIR / schema_file).read_text(encoding="utf-8"))
    return set(data.get("required", []))


def validate_rows(streams: dict[str, Any], root: Path) -> list[str]:
    """Return a list of structural errors (missing required fields)."""
    errors: list[str] = []
    for stream, (schema_file, _out) in STREAMS.items():
        required = _required(schema_file, root)
        for i, row in enumerate(streams[stream], start=1):
            missing = [f for f in required if f not in row or row[f] in (None, "")]
            # 'synthetic' is a required bool whose valid value False is "empty"-like
            missing = [f for f in missing if not (f == "synthetic" and row.get(f) is False)]
            if missing:
                errors.append(f"[{stream}:{i}] missing required: {missing}")
    return errors


def write_streams(streams: dict[str, Any], root: Path) -> dict[str, Any]:
    out = root / OUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    for stream, (_schema, out_file) in STREAMS.items():
        with (out / out_file).open("w", encoding="utf-8") as fh:
            for row in streams[stream]:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    manifest = {
        "producer_script": "scripts/bridge_canonical_v1_federation.py",
        "producer_phase": "CANONICAL_V1_FEDERATION_BRIDGE",
        "gate": "NON_PRODUCTION_DIAGNOSTIC",
        "stream_counts": {s: len(streams[s]) for s in STREAMS},
        "source_feeds": {
            "federal_publications": sum(
                1
                for s in streams["sources"]
                if (s.get("lineage") or {}).get("producer_phase") == FEDERAL_PUBLICATIONS_PHASE
            ),
            "canonical_v1_evidence": sum(
                1
                for s in streams["sources"]
                if (s.get("lineage") or {}).get("producer_phase") != FEDERAL_PUBLICATIONS_PHASE
            ),
        },
        "not_yet_federated_count": len(streams["not_yet_federated"]),
        "edges_federated_pct": round(
            100.0
            * len(streams["relationships"])
            / max(1, len(streams["relationships"]) + len(streams["not_yet_federated"])),
            2,
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bridge canonical_v1 to federation JSONL streams.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--check", action="store_true", help="Validate without writing.")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()

    streams = build_streams(root)
    n_pubs = merge_external_sources(streams, root)
    errors = validate_rows(streams, root)
    if errors:
        print(json.dumps({"ok": False, "errors": errors[:50]}, indent=2))
        return 1
    if args.check:
        print(
            json.dumps(
                {
                    "ok": True,
                    "stream_counts": {s: len(streams[s]) for s in STREAMS},
                    "federal_publications_added": n_pubs,
                    "not_yet_federated": len(streams["not_yet_federated"]),
                },
                indent=2,
            )
        )
        return 0
    print(json.dumps(write_streams(streams, root), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
