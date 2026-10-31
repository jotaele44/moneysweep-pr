from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

QUERY_STATUSES = {
    "PLANNED",
    "RUNNING",
    "SUCCESS",
    "SUCCESS_NULL",
    "FAILED_TRANSIENT",
    "FAILED_PERMANENT",
    "BLOCKED_AUTH",
    "BLOCKED_WAF",
    "BLOCKED_NETWORK",
    "RECORD_PURGED",
    "REQUIRES_BROWSER",
    "REQUIRES_FOIA",
}
REVIEW_STATUSES = {
    "UNREVIEWED",
    "MACHINE_VALIDATED",
    "HUMAN_REVIEWED",
    "CONTRADICTED",
    "SUPERSEDED",
    "REJECTED",
}
TRIGGER_CLASSES = {
    "FALSE_ENTITY_MERGE",
    "FALSE_CONTRACT_JOIN",
    "IDENTIFIER_COLLISION",
    "SOURCE_FORMAT_CHANGE",
    "PARSER_MISS",
    "MISSING_SCHEMA_FIELD",
    "REPEATED_QUERY",
    "UNHANDLED_FAILURE",
    "COVERAGE_OVERSTATEMENT",
    "COVERAGE_UNDERSTATEMENT",
    "SUCCESSOR_ATTRIBUTION_ERROR",
    "AMOUNT_SEMANTICS_ERROR",
}
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _sql_identifier(value: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"Unsafe SQL identifier: {value!r}")
    return value


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().upper().replace("&", " AND ").split())


def canonical_hash(*parts: Any, prefix: str = "") -> str:
    payload = "\x1f".join(_norm(p) for p in parts)
    return f"{prefix}{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def entity_id(jurisdiction: str, legal_name: str, authoritative_id: str | None = None) -> str:
    return canonical_hash(authoritative_id or jurisdiction, legal_name, prefix="ent_")


def pr_contract_action_key(
    issuing_entity_id: str,
    base_contract_number: str,
    amendment: str | None,
    contractor_entity_id: str,
) -> str:
    return canonical_hash(
        issuing_entity_id,
        base_contract_number,
        amendment or "BASE",
        contractor_entity_id,
        prefix="prc_",
    )


def federal_award_key(
    award_id_or_piid: str, recipient_entity_id: str, awarding_subagency: str
) -> str:
    return canonical_hash(award_id_or_piid, recipient_entity_id, awarding_subagency, prefix="faw_")


def evidence_key(source_hash: str, locator: str, claim: str) -> str:
    return canonical_hash(source_hash, locator, claim, prefix="ev_")


def query_key(
    source_id: str, subject_id: str, query_type: str, parameters: Mapping[str, Any]
) -> str:
    params = json.dumps(parameters, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return canonical_hash(source_id, subject_id, query_type, params, prefix="qry_")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class QueryDecision:
    action: str
    reason: str
    fallback_route: str | None = None


class ForensicsLedger:
    """DuckDB-backed, idempotent, provenance-preserving forensic ledger."""

    def __init__(self, db_path: str | Path, migrations_dir: str | Path | None = None) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = duckdb.connect(str(self.db_path))
        self.migrations_dir = (
            Path(migrations_dir)
            if migrations_dir
            else Path(__file__).resolve().parents[2] / "migrations" / "forensics"
        )

    def __enter__(self) -> "ForensicsLedger":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self.conn.close()

    def migrate(self) -> None:
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations(version VARCHAR PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL)"
        )
        applied = {
            row[0] for row in self.conn.execute("SELECT version FROM schema_migrations").fetchall()
        }
        for path in sorted(self.migrations_dir.glob("*.sql")):
            if path.stem in applied:
                continue
            self.conn.execute("BEGIN")
            try:
                self.conn.execute(path.read_text(encoding="utf-8"))
                self.conn.execute(
                    "INSERT INTO schema_migrations VALUES (?, ?)", [path.stem, utcnow()]
                )
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise

    def table_count(self, table: str) -> int:
        table = _sql_identifier(table)
        row = self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        return int(row[0]) if row else 0

    def upsert(
        self, table: str, records: Iterable[Mapping[str, Any]], key_columns: list[str]
    ) -> dict[str, int]:
        table = _sql_identifier(table)
        keys = [_sql_identifier(c) for c in key_columns]
        rows = [dict(r) for r in records]
        if not rows:
            return {"inserted": 0, "updated": 0, "unchanged": 0}
        columns = [_sql_identifier(c) for c in rows[0]]
        if any(set(r) != set(columns) for r in rows):
            raise ValueError("All upsert records must have identical columns")
        missing = set(keys) - set(columns)
        if missing:
            raise ValueError(f"Missing key columns: {sorted(missing)}")

        existing_rows = self.conn.execute(f"SELECT {','.join(columns)} FROM {table}").fetchall()
        existing = {tuple(row[columns.index(k)] for k in keys): tuple(row) for row in existing_rows}
        incoming_by_key = {tuple(r[k] for k in keys): tuple(r[c] for c in columns) for r in rows}
        inserted = sum(k not in existing for k in incoming_by_key)
        updated = sum(k in existing and existing[k] != v for k, v in incoming_by_key.items())
        unchanged = len(incoming_by_key) - inserted - updated

        arrow = pa.Table.from_pylist(rows)
        self.conn.register("_incoming", arrow)
        try:
            join = " AND ".join(f"t.{c}=s.{c}" for c in keys)
            updates = [c for c in columns if c not in keys]
            if updates:
                changed = " OR ".join(f"t.{c} IS DISTINCT FROM s.{c}" for c in updates)
                set_clause = ", ".join(f"{c}=s.{c}" for c in updates)
                self.conn.execute(
                    f"UPDATE {table} t SET {set_clause} FROM _incoming s WHERE {join} AND ({changed})"
                )
            cols = ",".join(columns)
            self.conn.execute(
                f"INSERT INTO {table} ({cols}) SELECT {cols} FROM _incoming s "
                f"WHERE NOT EXISTS (SELECT 1 FROM {table} t WHERE {join})"
            )
        finally:
            self.conn.unregister("_incoming")
        return {"inserted": inserted, "updated": updated, "unchanged": unchanged}

    def preflight_query(
        self,
        *,
        source_id: str,
        subject_id: str,
        query_type: str,
        parameters: Mapping[str, Any],
        aliases_changed: bool = False,
        contradiction_open: bool = False,
        now: datetime | None = None,
    ) -> QueryDecision:
        key = query_key(source_id, subject_id, query_type, parameters)
        row = self.conn.execute(
            "SELECT status, fresh_until, fallback_route, retry_after FROM query_history "
            "WHERE query_key=? ORDER BY finished_at DESC NULLS LAST LIMIT 1",
            [key],
        ).fetchone()
        if row is None:
            return QueryDecision("RUN", "never_executed")
        status, fresh_until, fallback, retry_after = row
        now = now or utcnow()
        if aliases_changed:
            return QueryDecision("RUN", "alias_or_identifier_set_changed")
        if contradiction_open:
            return QueryDecision("RUN", "open_contradiction")
        if retry_after is not None and retry_after > now:
            return QueryDecision("SKIP", "retry_window_not_reached", fallback)
        if status in {"FAILED_TRANSIENT", "BLOCKED_WAF", "BLOCKED_NETWORK", "BLOCKED_AUTH"}:
            return QueryDecision("RUN", "previous_route_failed", fallback)
        if fresh_until is not None and fresh_until > now and status in {"SUCCESS", "SUCCESS_NULL"}:
            return QueryDecision("SKIP", "successful_and_fresh")
        return QueryDecision("RUN", "stale_or_incomplete")

    def record_query(self, record: Mapping[str, Any]) -> dict[str, int]:
        if record["status"] not in QUERY_STATUSES:
            raise ValueError(f"Unsupported query status: {record['status']}")
        return self.upsert("query_history", [record], ["query_id"])

    def calculate_coverage(
        self, entity: str, domain: str, items: Iterable[Mapping[str, Any]]
    ) -> dict[str, Any]:
        rows = list(items)
        applicable = [r for r in rows if r.get("gap_status") != "NOT_APPLICABLE"]
        structurally_unavailable = {
            "SEALED_OR_CONFIDENTIAL",
            "RECORD_PURGED",
            "SOURCE_INACCESSIBLE",
        }
        resolvable = [r for r in applicable if r.get("gap_status") not in structurally_unavailable]
        public_score = sum(float(r.get("weight", 0)) for r in applicable)
        resolvable_score = sum(float(r.get("weight", 0)) for r in resolvable)
        result = {
            "entity_id": entity,
            "domain": domain,
            "required_items": len(applicable),
            "resolved_weight": public_score,
            "public_data_coverage": public_score / len(applicable) if applicable else 1.0,
            "resolvable_coverage": resolvable_score / len(resolvable) if resolvable else 1.0,
            "domain_confidence": sum(float(r.get("confidence", 0)) for r in applicable)
            / len(applicable)
            if applicable
            else 1.0,
            "blockers_json": json.dumps(
                sorted(
                    {
                        r.get("gap_status")
                        for r in applicable
                        if r.get("weight", 0) < 1 and r.get("gap_status")
                    }
                )
            ),
            "next_actions_json": json.dumps(
                [r.get("next_action") for r in applicable if r.get("next_action")]
            ),
            "updated_at": utcnow(),
        }
        self.upsert("coverage_state", [result], ["entity_id", "domain"])
        return result

    def recalculate_priorities(
        self, rows: Iterable[Mapping[str, Any]], weights: Mapping[str, float]
    ) -> list[dict[str, Any]]:
        old_ranks = dict(
            self.conn.execute("SELECT entity_id,current_rank FROM entity_priority_queue").fetchall()
        )
        now = utcnow()
        records = []
        for item in rows:
            metrics = item.get("metrics", {})
            score = sum(
                max(0.0, min(100.0, float(metrics.get(k, 0)))) * float(w)
                for k, w in weights.items()
            )
            records.append(
                {
                    "entity_id": item["entity_id"],
                    "current_rank": None,
                    "previous_rank": old_ranks.get(item["entity_id"]),
                    "rank_delta": None,
                    "priority_score": score,
                    "coverage_deficit": float(metrics.get("coverage_deficit", 0)),
                    "last_researched_at": item.get("last_researched_at"),
                    "staleness_score": float(metrics.get("staleness", 0)),
                    "priority_reasons_json": json.dumps(
                        sorted(metrics, key=lambda k: metrics[k], reverse=True)[:5]
                    ),
                    "highest_value_next_action": item.get("highest_value_next_action"),
                    "estimated_recovery_gain": float(metrics.get("estimated_recovery_gain", 0)),
                    "updated_at": now,
                }
            )
        self.upsert("entity_priority_queue", records, ["entity_id"])
        ranked = self.conn.execute(
            "SELECT entity_id FROM entity_priority_queue ORDER BY priority_score DESC, entity_id"
        ).fetchall()
        output = []
        for rank, (eid,) in enumerate(ranked, 1):
            previous = old_ranks.get(eid)
            delta = None if previous is None else previous - rank
            self.conn.execute(
                "UPDATE entity_priority_queue SET current_rank=?, previous_rank=?, rank_delta=? WHERE entity_id=?",
                [rank, previous, delta, eid],
            )
            output.append(
                {
                    "entity_id": eid,
                    "current_rank": rank,
                    "previous_rank": previous,
                    "rank_delta": delta,
                }
            )
        return output

    def recalculate_priority(
        self,
        entity: str,
        metrics: Mapping[str, float],
        weights: Mapping[str, float],
        previous_rank: int | None = None,
    ) -> float:
        self.recalculate_priorities([{"entity_id": entity, "metrics": metrics}], weights)
        row = self.conn.execute(
            "SELECT priority_score FROM entity_priority_queue WHERE entity_id=?", [entity]
        ).fetchone()
        return float(row[0]) if row else 0.0

    def export_parquet(
        self, output_dir: str | Path, tables: Iterable[str] | None = None
    ) -> list[Path]:
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        if tables is None:
            tables = [
                r[0]
                for r in self.conn.execute("SHOW TABLES").fetchall()
                if r[0] != "schema_migrations"
            ]
        written = []
        for table in sorted(tables):
            table = _sql_identifier(table)
            target = output / f"{table}.parquet"
            tmp = target.with_suffix(".parquet.tmp")
            arrow = self.conn.execute(f"SELECT * FROM {table} ORDER BY ALL").to_arrow_table()
            pq.write_table(arrow, tmp, compression="zstd", use_dictionary=True)
            tmp.replace(target)
            written.append(target)
        return written

    def propose_skill_improvement(self, proposal: Mapping[str, Any]) -> dict[str, int]:
        if proposal["problem_type"] not in TRIGGER_CLASSES:
            raise ValueError("Unsupported improvement trigger")
        if not proposal.get("evidence_ids_json"):
            raise ValueError("Skill proposals require triggering evidence")
        return self.upsert("skill_improvement_proposals", [proposal], ["proposal_id"])
