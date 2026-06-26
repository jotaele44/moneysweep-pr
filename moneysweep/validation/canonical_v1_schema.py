"""Canonical Entity Relationship Model v1 — schema & integrity validator.

Stdlib-only (no `jsonschema` dependency). Validates the `data/canonical_v1/`
CSV tables against the draft-07 JSON Schemas in `schemas/canonical_v1/`,
interpreting the subset of JSON Schema the model uses: ``required``, ``type``
(string/number/integer/boolean), ``enum``, ``pattern``, ``minLength``,
``minimum``/``maximum``.

Because CSV cells are always strings, an empty cell is treated as an absent
field (so optional-but-blank columns never fail). Beyond per-row schema
validation this module also enforces three model invariants:

* **Referential integrity** — every foreign key resolves to an existing
  primary key (``no broken reference``).
* **Controlled-vocabulary gate** — ``edges.edge_type`` must be one of the 15
  approved verbs (``no unknown verb``); offenders are reported for routing to
  ``review_queue.csv``.
* **Evidence-presence gate** — every edge carries a non-empty ``evidence_id``
  that resolves to an ``evidence.csv`` row (``no provenance -> no edge``).

CLI::

    python -m moneysweep.validation.canonical_v1_schema --root . [--allow-failed] [--json]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = "schemas/canonical_v1"
DATA_DIR = "data/canonical_v1"

# table -> (schema filename, csv filename, primary-key column)
TABLES: dict[str, tuple[str, str, str]] = {
    "people": ("people.schema.json", "people.csv", "person_id"),
    "entities": ("entities.schema.json", "entities.csv", "entity_id"),
    "roles": ("roles.schema.json", "roles.csv", "role_id"),
    "contracts": ("contracts.schema.json", "contracts.csv", "contract_id"),
    "projects": ("projects.schema.json", "projects.csv", "project_id"),
    "debt_instruments": ("debt_instruments.schema.json", "debt_instruments.csv", "debt_id"),
    "lobbying_records": (
        "lobbying_records.schema.json",
        "lobbying_records.csv",
        "lobbying_record_id",
    ),
    "funding_sources": ("funding_sources.schema.json", "funding_sources.csv", "funding_source_id"),
    "properties": ("properties.schema.json", "properties.csv", "property_id"),
    "municipalities": ("municipalities.schema.json", "municipalities.csv", "municipality_id"),
    "edges": ("edges.schema.json", "edges.csv", "edge_id"),
    "evidence": ("evidence.schema.json", "evidence.csv", "evidence_id"),
    "review_queue": ("review_queue.schema.json", "review_queue.csv", "review_id"),
}

# Foreign keys on the node/edge tables: column -> referenced table.
FOREIGN_KEYS: dict[str, dict[str, str]] = {
    "people": {"primary_entity_id": "entities", "evidence_id": "evidence"},
    "entities": {"parent_entity_id": "entities", "evidence_id": "evidence"},
    "roles": {"person_id": "people", "entity_id": "entities", "evidence_id": "evidence"},
    "contracts": {
        "awarding_entity_id": "entities",
        "contractor_entity_id": "entities",
        "project_id": "projects",
        "evidence_id": "evidence",
    },
    "projects": {
        "lead_entity_id": "entities",
        "municipality_id": "municipalities",
        "funding_source_id": "funding_sources",
        "evidence_id": "evidence",
    },
    "debt_instruments": {"issuer_entity_id": "entities", "evidence_id": "evidence"},
    "lobbying_records": {
        "lobbyist_entity_id": "entities",
        "client_entity_id": "entities",
        "evidence_id": "evidence",
    },
    "funding_sources": {"administering_entity_id": "entities", "evidence_id": "evidence"},
    "properties": {
        "owner_entity_id": "entities",
        "municipality_id": "municipalities",
        "evidence_id": "evidence",
    },
    "municipalities": {"evidence_id": "evidence"},
    "edges": {"evidence_id": "evidence"},
}

# edges.source_node_type / target_node_type -> referenced table.
NODE_TYPE_TABLE: dict[str, str] = {
    "Person": "people",
    "Entity": "entities",
    "Contract": "contracts",
    "Project": "projects",
    "DebtInstrument": "debt_instruments",
    "LobbyingRecord": "lobbying_records",
    "FundingSource": "funding_sources",
    "Property": "properties",
    "Municipality": "municipalities",
}

EDGE_TYPES: tuple[str, ...] = (
    "HOLDS_ROLE_IN",
    "OWNS_OR_CONTROLS",
    "REPRESENTS",
    "ADVISES",
    "RECEIVES_CONTRACT",
    "FUNDED_BY",
    "LOCATED_IN",
    "HOLDS_DEBT",
    "NEGOTIATES_WITH",
    "SHARES_PERSONNEL_WITH",
    "LOBBIES_FOR",
    "BENEFITS_FROM",
    "COLLECTS_REVENUE",
    "ALLOCATES_REVENUE_TO",
    "PLEDGED_TO_DEBT",
)


@dataclass
class ValidationReport:
    """Accumulated validation outcome across all canonical_v1 tables."""

    errors: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def add(self, message: str) -> None:
        self.errors.append(message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "error_count": len(self.errors),
            "row_counts": self.counts,
            "errors": self.errors,
        }


# --------------------------------------------------------------------------- #
# JSON-Schema subset interpreter
# --------------------------------------------------------------------------- #


def load_schema(table: str, root: Path | None = None) -> dict[str, Any]:
    root = root or REPO_ROOT
    schema_file = TABLES[table][0]
    return json.loads((root / SCHEMA_DIR / schema_file).read_text(encoding="utf-8"))


def _check_value(value: str, prop: dict[str, Any]) -> str | None:
    """Validate a single non-empty CSV cell against a property schema.

    Returns an error string, or None when valid.
    """
    declared = prop.get("type")
    if declared in ("number", "integer"):
        try:
            num = float(value)
        except ValueError:
            return f"expected {declared}, got {value!r}"
        if declared == "integer" and not float(num).is_integer():
            return f"expected integer, got {value!r}"
        if "minimum" in prop and num < prop["minimum"]:
            return f"{num} < minimum {prop['minimum']}"
        if "maximum" in prop and num > prop["maximum"]:
            return f"{num} > maximum {prop['maximum']}"
        return None
    if declared == "boolean":
        if value.lower() not in ("true", "false", "1", "0"):
            return f"expected boolean, got {value!r}"
        return None
    # string-like
    if "enum" in prop and value not in prop["enum"]:
        return f"{value!r} not in enum {prop['enum']}"
    if "pattern" in prop and not re.fullmatch(prop["pattern"], value):
        return f"{value!r} does not match pattern {prop['pattern']}"
    if "minLength" in prop and len(value) < prop["minLength"]:
        return f"shorter than minLength {prop['minLength']}"
    return None


def validate_row(row: dict[str, str], schema: dict[str, Any]) -> list[str]:
    """Return a list of error strings for one row (empty == valid)."""
    errors: list[str] = []
    required = set(schema.get("required", []))
    props = schema.get("properties", {})

    def _cell(col: str) -> str:
        # CSV cells are strings, but in-memory rows may carry native types
        # (float confidence, bool current, ...) -> coerce for uniform checks.
        raw = row.get(col)
        return "" if raw is None else str(raw).strip()

    for col in required:
        if not _cell(col):
            errors.append(f"missing required field '{col}'")
    for col, prop in props.items():
        value = _cell(col)
        if value == "":
            continue  # empty CSV cell == absent; only `required` cares
        msg = _check_value(value, prop)
        if msg:
            errors.append(f"field '{col}': {msg}")
    return errors


# --------------------------------------------------------------------------- #
# CSV loading + table-level validation
# --------------------------------------------------------------------------- #


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def load_all_tables(root: Path | None = None) -> dict[str, list[dict[str, str]]]:
    root = root or REPO_ROOT
    return {t: _read_csv(root / DATA_DIR / TABLES[t][1]) for t in TABLES}


def validate_schema(
    tables: dict[str, list[dict[str, str]]], report: ValidationReport, root: Path | None = None
) -> None:
    for table, rows in tables.items():
        schema = load_schema(table, root)
        report.counts[table] = len(rows)
        for i, row in enumerate(rows, start=1):
            for msg in validate_row(row, schema):
                report.add(f"[{table}:{i}] {msg}")


def validate_referential_integrity(
    tables: dict[str, list[dict[str, str]]], report: ValidationReport
) -> None:
    pks: dict[str, set[str]] = {
        t: {
            (r.get(TABLES[t][2]) or "").strip() for r in rows if (r.get(TABLES[t][2]) or "").strip()
        }
        for t, rows in tables.items()
    }
    # Declared single-target foreign keys.
    for table, fkmap in FOREIGN_KEYS.items():
        for i, row in enumerate(tables.get(table, []), start=1):
            for col, target in fkmap.items():
                val = (row.get(col) or "").strip()
                if val and val not in pks.get(target, set()):
                    report.add(f"[{table}:{i}] broken reference '{col}'={val!r} -> {target}")
    # Edge endpoints resolve against the table named by their node_type.
    for i, row in enumerate(tables.get("edges", []), start=1):
        for type_col, id_col in (
            ("source_node_type", "source_node_id"),
            ("target_node_type", "target_node_id"),
        ):
            ntype = (row.get(type_col) or "").strip()
            nid = (row.get(id_col) or "").strip()
            if not ntype or not nid:
                continue
            target_table = NODE_TYPE_TABLE.get(ntype)
            if target_table is None:
                report.add(f"[edges:{i}] unknown {type_col}={ntype!r}")
            elif nid not in pks.get(target_table, set()):
                report.add(f"[edges:{i}] broken endpoint {id_col}={nid!r} -> {target_table}")


def validate_controlled_vocab(
    tables: dict[str, list[dict[str, str]]], report: ValidationReport
) -> list[dict[str, str]]:
    """Flag edges whose verb is outside the controlled vocabulary.

    Returns the offending rows so callers can route them to review_queue.
    """
    offenders: list[dict[str, str]] = []
    for i, row in enumerate(tables.get("edges", []), start=1):
        verb = (row.get("edge_type") or "").strip()
        if verb and verb not in EDGE_TYPES:
            report.add(f"[edges:{i}] uncontrolled edge_type {verb!r}")
            offenders.append(row)
    return offenders


def validate_evidence_presence(
    tables: dict[str, list[dict[str, str]]], report: ValidationReport
) -> None:
    """Enforce 'no provenance -> no edge': every edge needs a resolvable evidence_id."""
    evidence_ids = {(r.get("evidence_id") or "").strip() for r in tables.get("evidence", [])}
    for i, row in enumerate(tables.get("edges", []), start=1):
        ev = (row.get("evidence_id") or "").strip()
        if not ev:
            report.add(f"[edges:{i}] missing evidence_id (no provenance -> no edge)")
        elif ev not in evidence_ids:
            report.add(f"[edges:{i}] evidence_id={ev!r} not found in evidence table")


def validate_all(root: Path | None = None) -> ValidationReport:
    root = root or REPO_ROOT
    report = ValidationReport()
    tables = load_all_tables(root)
    validate_schema(tables, report, root)
    validate_referential_integrity(tables, report)
    validate_controlled_vocab(tables, report)
    validate_evidence_presence(tables, report)
    return report


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate Canonical Entity Relationship Model v1 tables."
    )
    parser.add_argument("--root", default=".", help="Repository root.")
    parser.add_argument(
        "--allow-failed", action="store_true", help="Report errors but exit 0 (bootstrap mode)."
    )
    parser.add_argument("--json", action="store_true", help="Emit a JSON report.")
    args = parser.parse_args(argv)

    report = validate_all(Path(args.root).resolve())

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(
            f"canonical_v1 validation: {'PASS' if report.ok else 'FAIL'} "
            f"({len(report.errors)} error(s); rows={report.counts})"
        )
        for err in report.errors[:200]:
            print(f"  - {err}")
        if len(report.errors) > 200:
            print(f"  ... and {len(report.errors) - 200} more")

    if report.ok or args.allow_failed:
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
