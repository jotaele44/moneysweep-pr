"""Build the top-form Person Master reference table (Gate 5, item ``person_master``).

The Person Master is the stable, schema-locked registry of the people the project
tracks — lobbyists, public officials, board members, and donors — drawn from the
curated, accepted rows of ``data/canonical_v1/people.csv``. It is a focused,
person-only sibling of the Entity Master: IDs follow the ``ENT_PERSON_<hash>``
convention in ``schemas/person_master.schema.json`` and every row carries an
evidence tier and confidence so downstream gates (influence edges, graph export,
contractor↔donor overlap) can resolve against a single person authority.

Source surface (committed, deterministic — no network): ``data/canonical_v1/people.csv``,
filtered to ``review_status == "accepted"``. The stable per-person hash from that
table is reused as the ``ENT_PERSON_`` suffix (guaranteeing uniqueness and
determinism), and the original ``person_id`` is carried as ``source_person_id`` so
the Person Master joins cleanly to ``canonical_v1/{people,roles,review_queue}.csv``.

Reuses the stdlib schema validator in
``moneysweep.validation.canonical_v1_schema`` (no ``jsonschema`` dep).

CLI::

    python scripts/build_person_master.py            # write the CSV + manifest
    python scripts/build_person_master.py --check     # validate without writing
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
PEOPLE = "data/canonical_v1/people.csv"
PERSON_MASTER_OUT = "data/reference/person_master.csv"
MANIFEST_OUT = "data/manifests/person_master.json"
SCHEMA = "schemas/person_master.schema.json"
SOURCE_ID = "canonical_v1_people"

# Output column order (schema required fields + carried provenance/notes).
PERSON_MASTER_COLUMNS = [
    "person_id",
    "canonical_name",
    "normalized_name",
    "jurisdiction",
    "source_person_id",
    "source_id",
    "evidence_tier",
    "confidence",
    "notes",
]

EVIDENCE_TIER = "T2"  # curated research registry (accepted rows), below official T1


def _load_schema(root: Path) -> dict[str, Any]:
    return json.loads((root / SCHEMA).read_text(encoding="utf-8"))


def _confidence(raw: str | None) -> float:
    if raw is None:
        return 0.5
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.5


def build_rows(root: Path | None = None) -> list[dict[str, Any]]:
    """Return Person Master rows from the accepted canonical_v1 people."""
    root = root or REPO_ROOT
    rows: list[dict[str, Any]] = []
    with (root / PEOPLE).open(newline="", encoding="utf-8") as fh:
        for ref in csv.DictReader(fh):
            source_pid = (ref.get("person_id") or "").strip()
            name = (ref.get("full_name") or "").strip()
            if not source_pid or not name:
                continue
            if (ref.get("review_status") or "").strip().lower() != "accepted":
                continue
            suffix = source_pid.removeprefix("person_")
            rows.append(
                {
                    "person_id": f"ENT_PERSON_{suffix}",
                    "canonical_name": name,
                    "normalized_name": (ref.get("normalized_name") or "").strip(),
                    "jurisdiction": (ref.get("jurisdiction") or "").strip() or "PR",
                    "source_person_id": source_pid,
                    "source_id": SOURCE_ID,
                    "evidence_tier": EVIDENCE_TIER,
                    "confidence": _confidence(ref.get("confidence")),
                    "notes": (ref.get("notes") or "").strip(),
                }
            )
    return rows


def check(rows: list[dict[str, Any]], root: Path | None = None) -> list[str]:
    """Return a list of problems (empty == valid)."""
    root = root or REPO_ROOT
    problems: list[str] = []
    if not rows:
        problems.append("no person_master rows produced")
    ids = [r["person_id"] for r in rows]
    if len(set(ids)) != len(ids):
        problems.append("duplicate person_id values present")
    schema = _load_schema(root)
    for i, row in enumerate(rows, start=1):
        for msg in validate_row(row, schema):
            problems.append(f"row {i} ({row.get('canonical_name')!r}): {msg}")
    return problems


def _write(rows: list[dict[str, Any]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=PERSON_MASTER_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def build(root: Path | None = None) -> dict[str, Any]:
    """Build, validate, and write the Person Master CSV + manifest."""
    root = root or REPO_ROOT
    rows = build_rows(root)
    problems = check(rows, root)
    if problems:
        raise ValueError("person_master check failed: " + "; ".join(problems))
    _write(rows, root / PERSON_MASTER_OUT)
    manifest = {
        "producer_script": "scripts/build_person_master.py",
        "producer_phase": "TOP_FORM_PERSON_MASTER",
        "schema": SCHEMA,
        "source_inputs": [PEOPLE],
        "output": PERSON_MASTER_OUT,
        "row_count": len(rows),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = root / MANIFEST_OUT
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the top-form Person Master reference table."
    )
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
