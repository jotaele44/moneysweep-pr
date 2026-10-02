"""Runtime certification for the Case Manager SQLite database.

This certifier is intentionally byte-aware.  It refuses to certify a database
with an active WAL sidecar because hashing only the main ``.sqlite3`` file would
not represent the complete logical state.  Quiesce/checkpoint first, then run.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

EXPECTED_TABLES = {
    "cases",
    "case_evidence",
    "claims",
    "claim_evidence",
    "case_entities",
    "case_events",
    "contradictions",
    "leads",
    "findings",
    "case_snapshots",
    "case_audit_events",
}


@dataclass
class SQLiteReport:
    status: str = "PASS"
    database_path: str | None = None
    sha256: str | None = None
    size_bytes: int | None = None
    integrity_check: list[str] = field(default_factory=list)
    foreign_key_violations: list[list[Any]] = field(default_factory=list)
    table_names: list[str] = field(default_factory=list)
    dangling_evidence_refs: list[dict[str, Any]] = field(default_factory=list)
    audit_chain_issues: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "PASS" and not self.issues

    def fail(self, message: str) -> None:
        self.issues.append(message)
        self.status = "FAIL"

    def block(self, message: str) -> None:
        self.issues.append(message)
        self.status = "BLOCKED"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "database_path": self.database_path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "integrity_check": self.integrity_check,
            "foreign_key_violations": self.foreign_key_violations,
            "table_names": self.table_names,
            "dangling_evidence_refs": self.dangling_evidence_refs,
            "audit_chain_issues": self.audit_chain_issues,
            "issues": self.issues,
        }


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _canonical_evidence_ids(path: Path) -> set[str]:
    with path.open(newline="", encoding="utf-8") as fh:
        return {
            (row.get("evidence_id") or "").strip()
            for row in csv.DictReader(fh)
            if (row.get("evidence_id") or "").strip()
        }


def _json_ids(raw: str | None) -> list[str]:
    if not raw:
        return []
    value = json.loads(raw)
    if not isinstance(value, list):
        raise ValueError("expected JSON array")
    return [str(item) for item in value]


def _check_evidence_refs(
    connection: sqlite3.Connection, evidence_ids: set[str], report: SQLiteReport
) -> None:
    direct = (
        ("case_evidence", "case_evidence_id", "evidence_id"),
        ("claim_evidence", "claim_evidence_id", "evidence_id"),
    )
    for table, id_col, evidence_col in direct:
        for row in connection.execute(f"SELECT {id_col},{evidence_col} FROM {table}"):
            evidence_id = str(row[evidence_col])
            if evidence_id not in evidence_ids:
                report.dangling_evidence_refs.append(
                    {"table": table, "object_id": row[id_col], "evidence_id": evidence_id}
                )

    arrays = (
        ("case_events", "case_event_id", "source_evidence_ids_json"),
        ("leads", "lead_id", "closure_evidence_ids_json"),
        ("case_snapshots", "case_snapshot_id", "evidence_ids_json"),
    )
    for table, id_col, json_col in arrays:
        for row in connection.execute(f"SELECT {id_col},{json_col} FROM {table}"):
            try:
                refs = _json_ids(row[json_col])
            except Exception as exc:
                report.fail(f"{table}:{row[id_col]} invalid {json_col}: {exc}")
                continue
            for evidence_id in refs:
                if evidence_id not in evidence_ids:
                    report.dangling_evidence_refs.append(
                        {"table": table, "object_id": row[id_col], "evidence_id": evidence_id}
                    )
    if report.dangling_evidence_refs:
        report.fail(
            f"{len(report.dangling_evidence_refs)} dangling canonical evidence reference(s)"
        )


def _check_audit_chains(connection: sqlite3.Connection, report: SQLiteReport) -> None:
    case_ids = [
        row[0]
        for row in connection.execute(
            "SELECT DISTINCT case_id FROM case_audit_events ORDER BY case_id"
        ).fetchall()
    ]
    for case_id in case_ids:
        rows = connection.execute(
            "SELECT sequence,payload_sha256,previous_event_sha256 "
            "FROM case_audit_events WHERE case_id=? ORDER BY sequence",
            (case_id,),
        ).fetchall()
        previous_hash = None
        for expected_sequence, row in enumerate(rows, start=1):
            if row["sequence"] != expected_sequence:
                report.audit_chain_issues.append(
                    f"{case_id}: sequence {row['sequence']} != expected {expected_sequence}"
                )
            if row["previous_event_sha256"] != previous_hash:
                report.audit_chain_issues.append(
                    f"{case_id}:{row['sequence']}: predecessor hash mismatch"
                )
            previous_hash = row["payload_sha256"]
    if report.audit_chain_issues:
        report.fail(f"{len(report.audit_chain_issues)} audit-chain issue(s)")


def certify_sqlite(
    database_path: Path,
    canonical_evidence_path: Path,
) -> SQLiteReport:
    report = SQLiteReport(database_path=str(database_path))
    if not database_path.exists():
        report.block("runtime SQLite database is not available")
        return report
    wal = Path(str(database_path) + "-wal")
    if wal.exists() and wal.stat().st_size:
        report.block(
            "active SQLite WAL sidecar present; checkpoint/quiesce before byte certification"
        )
        return report
    if not canonical_evidence_path.exists():
        report.block("canonical evidence catalog is not available")
        return report

    report.sha256 = _sha256(database_path)
    report.size_bytes = database_path.stat().st_size
    uri = f"file:{database_path.resolve()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        report.integrity_check = [row[0] for row in connection.execute("PRAGMA integrity_check")]
        if report.integrity_check != ["ok"]:
            report.fail(f"PRAGMA integrity_check failed: {report.integrity_check}")

        report.foreign_key_violations = [
            list(row) for row in connection.execute("PRAGMA foreign_key_check").fetchall()
        ]
        if report.foreign_key_violations:
            report.fail(
                f"PRAGMA foreign_key_check found {len(report.foreign_key_violations)} violation(s)"
            )

        report.table_names = sorted(
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        )
        missing = sorted(EXPECTED_TABLES - set(report.table_names))
        if missing:
            report.fail(f"required Case Manager tables missing: {missing}")

        if not missing:
            _check_evidence_refs(
                connection, _canonical_evidence_ids(canonical_evidence_path), report
            )
            _check_audit_chains(connection, report)
    finally:
        connection.close()

    # Detect byte mutation during certification.
    if report.sha256 != _sha256(database_path):
        report.fail("SQLite bytes changed during certification")
    return report
