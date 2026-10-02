"""SQLite persistence adapter for Case Manager Phase 1."""

from __future__ import annotations

import csv
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Iterator, Sequence, cast


class CaseManagerConflict(RuntimeError):
    """A transactional invariant or optimistic sequence check failed."""


class CaseManagerNotFound(LookupError):
    """A requested Case Manager object does not exist."""


class SQLiteCaseManagerRepository:
    """Explicit SQLite repository with no canonical-evidence write capability.

    File-backed production repositories automatically bind the read-only
    canonical evidence catalog. In-memory repositories leave it unconfigured so
    unit tests can remain isolated unless they opt in explicitly.
    """

    def __init__(
        self,
        database: str | Path | sqlite3.Connection,
        *,
        canonical_evidence_path: str | Path | None = None,
    ):
        if isinstance(database, sqlite3.Connection):
            self.connection = database
            self._owns_connection = False
        else:
            self.connection = sqlite3.connect(str(database), check_same_thread=False)
            self._owns_connection = True
            if canonical_evidence_path is None:
                canonical_evidence_path = (
                    Path(__file__).resolve().parents[2] / "data" / "canonical_v1" / "evidence.csv"
                )
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.canonical_evidence_path = (
            Path(canonical_evidence_path) if canonical_evidence_path is not None else None
        )
        self._evidence_cache_signature: tuple[int, int] | None = None
        self._evidence_ids: set[str] = set()

    def close(self) -> None:
        if self._owns_connection:
            self.connection.close()

    def apply_migration(self, migration_path: str | Path) -> None:
        self.connection.executescript(Path(migration_path).read_text())

    @contextmanager
    def transaction(self, *, immediate: bool = True) -> Iterator[sqlite3.Connection]:
        try:
            self.connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield self.connection
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    @staticmethod
    def _payload(record: Any) -> dict[str, Any]:
        if not is_dataclass(record) or isinstance(record, type):
            raise TypeError("record must be a dataclass instance")
        return asdict(cast(Any, record))

    @staticmethod
    def _json(value: Sequence[str]) -> str:
        return json.dumps(list(value), separators=(",", ":"), sort_keys=True)

    @staticmethod
    def _insert(connection: sqlite3.Connection, table: str, values: dict[str, Any]) -> None:
        """Insert by explicit column name so dataclass/schema order cannot corrupt rows."""
        if not values:
            raise ValueError("insert requires at least one column")
        columns = tuple(values)
        if any(not column.replace("_", "").isalnum() for column in columns):
            raise ValueError("unsafe column name")
        placeholders = ",".join("?" for _ in columns)
        names = ",".join(columns)
        connection.execute(
            f"INSERT INTO {table} ({names}) VALUES({placeholders})",
            tuple(values[column] for column in columns),
        )

    def canonical_evidence_exists(self, evidence_id: str) -> bool | None:
        """Return True/False when a canonical evidence catalog is configured.

        ``None`` means no catalog was configured (allowed for isolated tests but
        not used by the production API boundary).
        """
        path = self.canonical_evidence_path
        if path is None:
            return None
        if not path.exists():
            return False
        stat = path.stat()
        signature = (stat.st_mtime_ns, stat.st_size)
        if signature != self._evidence_cache_signature:
            with path.open(newline="", encoding="utf-8") as fh:
                self._evidence_ids = {
                    (row.get("evidence_id") or "").strip()
                    for row in csv.DictReader(fh)
                    if (row.get("evidence_id") or "").strip()
                }
            self._evidence_cache_signature = signature
        return evidence_id in self._evidence_ids

    def insert_case(self, record: Any, connection: sqlite3.Connection) -> None:
        self._insert(connection, "cases", self._payload(record))

    def insert_case_evidence(self, record: Any, connection: sqlite3.Connection) -> None:
        self._insert(connection, "case_evidence", self._payload(record))

    def insert_claim(self, record: Any, connection: sqlite3.Connection) -> None:
        self._insert(connection, "claims", self._payload(record))

    def insert_claim_evidence(self, record: Any, connection: sqlite3.Connection) -> None:
        self._insert(connection, "claim_evidence", self._payload(record))

    def insert_contradiction(self, record: Any, connection: sqlite3.Connection) -> None:
        p = self._payload(record)
        self._insert(
            connection,
            "contradictions",
            {
                "contradiction_id": p["contradiction_id"],
                "case_id": p["case_id"],
                "claim_ids_json": self._json(p["claim_ids"]),
                "contradiction_type": p["contradiction_type"],
                "severity": p["severity"],
                "status": p["status"],
                "resolution_rationale": p["resolution_rationale"],
                "assigned_reviewer": p["assigned_reviewer"],
                "visibility": p["visibility"],
            },
        )

    def resolve_contradiction(
        self,
        contradiction_id: str,
        status: str,
        rationale: str,
        reviewer: str,
        connection: sqlite3.Connection,
    ) -> None:
        result = connection.execute(
            "UPDATE contradictions SET status=?,resolution_rationale=?,assigned_reviewer=? "
            "WHERE contradiction_id=? AND status='open'",
            (status, rationale, reviewer, contradiction_id),
        )
        if result.rowcount != 1:
            raise CaseManagerConflict("contradiction is missing or no longer open")

    def insert_lead(self, record: Any, connection: sqlite3.Connection) -> None:
        p = self._payload(record)
        self._insert(
            connection,
            "leads",
            {
                "lead_id": p["lead_id"],
                "case_id": p["case_id"],
                "question": p["question"],
                "status": p["status"],
                "acquisition_target": p["acquisition_target"],
                "owner": p["owner"],
                "due_at": p["due_at"],
                "closure_evidence_ids_json": self._json(p["closure_evidence_ids"]),
                "visibility": p["visibility"],
            },
        )

    def close_lead(
        self,
        lead_id: str,
        closure_evidence_ids: Sequence[str],
        connection: sqlite3.Connection,
    ) -> None:
        result = connection.execute(
            "UPDATE leads SET status='closed',closure_evidence_ids_json=? "
            "WHERE lead_id=? AND status!='closed'",
            (self._json(closure_evidence_ids), lead_id),
        )
        if result.rowcount != 1:
            raise CaseManagerConflict("lead is missing or already closed")

    def insert_finding(self, record: Any, connection: sqlite3.Connection) -> None:
        p = self._payload(record)
        self._insert(
            connection,
            "findings",
            {
                "finding_id": p["finding_id"],
                "case_id": p["case_id"],
                "claim_id": p["claim_id"],
                "conclusion": p["conclusion"],
                "confidence": p["confidence"],
                "reviewer": p["reviewer"],
                "contradiction_reviewed": int(p["contradiction_reviewed"]),
                "status": p["status"],
                "visibility": p["visibility"],
            },
        )

    def accept_finding(self, finding_id: str, connection: sqlite3.Connection) -> None:
        result = connection.execute(
            "UPDATE findings SET status='accepted' "
            "WHERE finding_id=? AND status='draft' AND contradiction_reviewed=1",
            (finding_id,),
        )
        if result.rowcount != 1:
            raise CaseManagerConflict("finding cannot be accepted")

    def insert_snapshot(self, record: Any, connection: sqlite3.Connection) -> None:
        p = self._payload(record)
        self._insert(
            connection,
            "case_snapshots",
            {
                "case_snapshot_id": p["case_snapshot_id"],
                "case_id": p["case_id"],
                "created_at": p["created_at"],
                "manifest_sha256": p["manifest_sha256"],
                "evidence_ids_json": self._json(p["evidence_ids"]),
                "supersedes_snapshot_id": p["supersedes_snapshot_id"],
                "redaction_profile": p["redaction_profile"],
                "visibility": p["visibility"],
            },
        )

    def append_audit_event(
        self,
        event: Any,
        expected_previous_sequence: int,
        connection: sqlite3.Connection,
    ) -> None:
        p = self._payload(event)
        row = connection.execute(
            "SELECT sequence,payload_sha256 FROM case_audit_events WHERE case_id=? "
            "ORDER BY sequence DESC LIMIT 1",
            (p["case_id"],),
        ).fetchone()
        current_sequence = int(row["sequence"]) if row else 0
        previous_hash = row["payload_sha256"] if row else None
        if current_sequence != expected_previous_sequence:
            raise CaseManagerConflict("audit sequence changed concurrently")
        if p["sequence"] != current_sequence + 1:
            raise CaseManagerConflict("audit sequence is not contiguous")
        if p["previous_event_sha256"] != previous_hash:
            raise CaseManagerConflict("audit predecessor hash mismatch")
        self._insert(connection, "case_audit_events", p)

    def latest_audit(self, case_id: str) -> tuple[int, str | None]:
        row = self.connection.execute(
            "SELECT sequence,payload_sha256 FROM case_audit_events WHERE case_id=? "
            "ORDER BY sequence DESC LIMIT 1",
            (case_id,),
        ).fetchone()
        return (int(row["sequence"]), row["payload_sha256"]) if row else (0, None)

    def fetch_one(self, table: str, id_column: str, object_id: str) -> dict[str, Any]:
        allowed = {
            "cases",
            "case_evidence",
            "claims",
            "claim_evidence",
            "contradictions",
            "leads",
            "findings",
            "case_snapshots",
            "case_audit_events",
            "case_events",
        }
        if table not in allowed:
            raise ValueError("unsupported table")
        row = self.connection.execute(
            f"SELECT * FROM {table} WHERE {id_column}=?", (object_id,)
        ).fetchone()
        if row is None:
            raise CaseManagerNotFound(object_id)
        return dict(row)

    def fetch_case_rows(self, table: str, case_id: str) -> list[dict[str, Any]]:
        allowed = {
            "case_evidence",
            "claims",
            "contradictions",
            "case_events",
            "leads",
            "findings",
            "case_snapshots",
            "case_audit_events",
        }
        if table not in allowed:
            raise ValueError("unsupported case table")
        order = "sequence" if table == "case_audit_events" else "rowid"
        rows = self.connection.execute(
            f"SELECT * FROM {table} WHERE case_id=? ORDER BY {order}", (case_id,)
        ).fetchall()
        return [dict(row) for row in rows]

    def list_cases(self) -> list[dict[str, Any]]:
        rows = self.connection.execute("SELECT * FROM cases ORDER BY opened_at,case_id").fetchall()
        return [dict(row) for row in rows]
