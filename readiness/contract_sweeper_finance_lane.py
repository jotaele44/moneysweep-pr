"""Contract-Sweeper politics / public-finance intake lane (issue #114).

Consumes the PR-intake router's Contract-Sweeper lane export
(``contract_sweeper_derivatives.csv``) and fans each derivative out into the
normalized finance tables + review queues that the router itself assigns via the
row's ``output_tables`` field (the authoritative routing decision made by
``shared/pr_intake_router.py`` against ``config/pr_intake_domain_router.yaml``).

This is the Contract-Sweeper counterpart to spiderweb-pr's
``readiness/spiderweb_spatial_lane.py`` and follows the same contract: stdlib
only, **zero-loss** (every input row lands in at least one normalized table or
review queue, or is recorded in the discrepancy queue — nothing is dropped),
and it returns a machine-readable report dict.

Finance records intentionally carry no geometry (lat/lon/CRS); spatial routing
is the spiderweb lane's job.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

INPUT_FILENAME = "contract_sweeper_derivatives.csv"
LANE_ID = "contract_sweeper_politics_finance_lane"
EXPORT_CONTRACT_VERSION = "1.0.0"
REPORT_FILENAME = "contract_sweeper_finance_lane_report.json"

# Authoritative table set, from config/pr_intake_domain_router.yaml (CS rules).
NORMALIZED_TABLES = (
    "funding_event_leads.csv",
    "contracts_procurement_events.csv",
    "politics_finance_items.csv",
    "agency_actions.csv",
    "lobbying_political_links.csv",
)
REVIEW_TABLES = (
    "verification_queue.csv",
    "contract_sweeper_crosswalk_queue.csv",
)
_NORMALIZED_SET = {t[:-4] for t in NORMALIZED_TABLES}   # strip .csv
_REVIEW_SET = {t[:-4] for t in REVIEW_TABLES}

# Finance record columns (a finance-relevant projection of the derivative — no
# geometry; spatial fields belong to the spiderweb lane).
FINANCE_FIELDS = (
    "record_id",
    "source_item_id",
    "canonical_repo",
    "related_repo_record_id",
    "source_name",
    "source_url",
    "published_at",
    "discovered_at",
    "title",
    "summary_own_words",
    "agency_entity",
    "municipality_name",
    "location_text",
    "topic_domains",
    "evidence_tier",
    "confidence_level",
    "source_hash",
    "content_hash",
    "dedupe_group_id",
    "final_status",
)
DISCREPANCY_FIELDS = ("source_item_id", "record_id", "review_reason")


class ContractSweeperFinanceLaneError(ValueError):
    """Raised when a required input is missing."""


def _parse_json_array(raw: str, field: str):
    raw = (raw or "").strip()
    if not raw:
        return [], None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"{field} is not valid JSON: {exc}"
    if not isinstance(value, list):
        return None, f"{field} must be a JSON array"
    return [str(v) for v in value], None


def _finance_record(row: dict[str, str], domains: list[str]) -> dict[str, str]:
    rec = {field: "" for field in FINANCE_FIELDS}
    for field in FINANCE_FIELDS:
        if field in row:
            rec[field] = row.get(field, "") or ""
    rec["topic_domains"] = json.dumps(domains)
    return rec


def _classify(row: dict[str, str]):
    """Return (record, normalized_targets, review_targets, errors)."""
    if not (row.get("record_id") or "").strip():
        return None, [], [], ["missing record_id"]

    domains, derr = _parse_json_array(row.get("domains", ""), "domains")
    if derr:
        return None, [], [], [derr]
    if not domains:
        return None, [], [], ["domains parsed to an empty array"]

    output_tables, oerr = _parse_json_array(row.get("output_tables", "") or "[]", "output_tables")
    if oerr:
        return None, [], [], [oerr]

    normalized = [t for t in output_tables if t in _NORMALIZED_SET]
    review = [t for t in output_tables if t in _REVIEW_SET]
    unknown = [t for t in output_tables if t not in _NORMALIZED_SET and t not in _REVIEW_SET]

    if not normalized and not review:
        reason = "no recognized output_tables"
        if unknown:
            reason += f" (unrecognized: {', '.join(sorted(unknown))})"
        return None, [], [], [reason]

    return _finance_record(row, domains), normalized, review, []


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build_contract_sweeper_finance_lane(input_dir, output_dir=None) -> dict[str, Any]:
    """Normalize the router's Contract-Sweeper derivatives into the finance lane.

    Reads ``contract_sweeper_derivatives.csv`` from *input_dir*, writes the
    normalized finance tables + review queues under *output_dir* (default:
    *input_dir*), and returns the report dict.
    """
    root = Path(input_dir)
    out = Path(output_dir) if output_dir else root
    source = root / INPUT_FILENAME
    if not source.exists():
        raise ContractSweeperFinanceLaneError(f"missing required input: {INPUT_FILENAME}")

    with source.open("r", encoding="utf-8", newline="") as f:
        rows = [dict(r) for r in csv.DictReader(f)]

    tables: dict[str, list[dict[str, Any]]] = {t[:-4]: [] for t in NORMALIZED_TABLES}
    review: dict[str, list[dict[str, Any]]] = {t[:-4]: [] for t in REVIEW_TABLES}
    discrepancy: list[dict[str, Any]] = []

    for row in rows:
        record, normalized_targets, review_targets, errors = _classify(row)
        if errors:
            discrepancy.append({
                "source_item_id": row.get("source_item_id", ""),
                "record_id": row.get("record_id", ""),
                "review_reason": "; ".join(errors),
            })
            continue
        for table in normalized_targets:
            tables[table].append(record)
        for queue in review_targets:
            review[queue].append(record)

    normalized_dir = out / "data" / "normalized"
    review_dir = out / "data" / "review"
    daily_dir = out / "reports" / "daily"
    for d in (normalized_dir, review_dir, daily_dir):
        d.mkdir(parents=True, exist_ok=True)

    for table in NORMALIZED_TABLES:
        name = table[:-4]
        _write_csv(normalized_dir / table, sorted(tables[name], key=lambda r: r["record_id"]), FINANCE_FIELDS)
    for queue in REVIEW_TABLES:
        name = queue[:-4]
        _write_csv(review_dir / queue, sorted(review[name], key=lambda r: r["record_id"]), FINANCE_FIELDS)
    _write_csv(review_dir / "discrepancy_queue.csv", discrepancy, DISCREPANCY_FIELDS)

    routed = sum(1 for r in rows) - len(discrepancy)
    normalized_count = sum(len(v) for v in tables.values())
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lane_id": LANE_ID,
        "input_dir": str(root),
        "producer": "pr-intake-router",
        "export_contract_version": EXPORT_CONTRACT_VERSION,
        "status": "READY" if routed else "EMPTY",
        "input_rows": len(rows),
        "routed_rows": routed,
        "normalized_writes": normalized_count,
        "by_table": {t[:-4]: len(tables[t[:-4]]) for t in NORMALIZED_TABLES},
        "by_review_queue": {t[:-4]: len(review[t[:-4]]) for t in REVIEW_TABLES},
        "discrepancy_count": len(discrepancy),
        # zero-loss: every input row is either routed (>=1 table/queue) or recorded
        # in the discrepancy queue — nothing silently dropped.
        "zero_loss_pass": routed + len(discrepancy) == len(rows),
        "outputs": {
            "normalized": [f"data/normalized/{t}" for t in NORMALIZED_TABLES],
            "review": [f"data/review/{t}" for t in REVIEW_TABLES] + ["data/review/discrepancy_queue.csv"],
            "daily_report": "reports/daily/politics_finance_update_report.md",
            "lane_report": REPORT_FILENAME,
        },
    }

    lines = [
        "# Contract-Sweeper Politics / Public-Finance Update",
        "",
        f"Generated at: {report['generated_at']}",
        f"Status: {report['status']} — zero-loss: {'PASS' if report['zero_loss_pass'] else 'FAIL'}",
        f"Input rows: {report['input_rows']} | routed: {report['routed_rows']} | discrepancy: {report['discrepancy_count']}",
        "",
        "## Normalized records by table",
    ]
    for name, count in sorted(report["by_table"].items()):
        lines.append(f"- `{name}`: {count}")
    lines += ["", "## Review queues"]
    for name, count in sorted(report["by_review_queue"].items()):
        lines.append(f"- `{name}`: {count}")
    lines.append(f"- `discrepancy_queue`: {report['discrepancy_count']}")
    lines.append("")
    (daily_dir / "politics_finance_update_report.md").write_text("\n".join(lines), encoding="utf-8")
    (out / REPORT_FILENAME).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report
