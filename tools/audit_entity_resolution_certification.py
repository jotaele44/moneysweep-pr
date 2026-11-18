#!/usr/bin/env python3
"""Audit G7 identity residue without treating evidence confidence as match ambiguity.

The historical entity review queue mechanically flags canonical people below a
confidence threshold. That is useful review evidence, but it is not equivalent to
an unresolved candidate match. For certification we conservatively distinguish:

* blocking review residue: non-advisory open reviews, canonical graph review rows,
  or a low-confidence advisory person referenced by a promoted canonical surface;
* advisory residue: an open low-confidence person row with no candidate match and
  no references outside its profile/evidence surfaces.

This tool never edits identities, closes reviews, or lowers confidence thresholds.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

CLOSED = {"closed", "resolved", "accepted"}
NON_RELATIONAL_CANONICAL = {"people.csv", "evidence.csv", "review_queue.csv"}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def is_open(row: dict[str, str]) -> bool:
    return row.get("status", "").strip().lower() not in CLOSED


def is_advisory_low_confidence(row: dict[str, str]) -> bool:
    return (
        row.get("issue_type", "").strip() == "low_confidence"
        and not row.get("candidate_match", "").strip()
        and row.get("object_type", "").strip() == "person"
    )


def find_references(root: Path, person_id: str) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    canonical = root / "data" / "canonical_v1"
    for path in sorted(canonical.glob("*.csv")):
        if path.name in NON_RELATIONAL_CANONICAL:
            continue
        try:
            rows = read_csv(path)
        except (OSError, UnicodeDecodeError, csv.Error):
            continue
        hits = 0
        columns: set[str] = set()
        for row in rows:
            for key, value in row.items():
                if value and person_id in value:
                    hits += 1
                    columns.add(key)
        if hits:
            refs.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "hits": hits,
                    "columns": sorted(columns),
                }
            )
    return refs


def build(root: Path) -> dict[str, Any]:
    review_path = root / "reports/entity_resolution_review_queue.csv"
    canonical_review_path = root / "data/canonical_v1/review_queue.csv"
    graph_path = root / "reports/canonical_v1_graph_summary.json"
    review_rows = read_csv(review_path)
    canonical_review_rows = read_csv(canonical_review_path)
    graph = json.loads(graph_path.read_text(encoding="utf-8"))

    canonical_paths = sorted((root / "data/canonical_v1").glob("*.csv"))
    input_paths = [review_path, graph_path, *canonical_paths]
    input_manifest = {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in input_paths
        if path.is_file()
    }

    open_rows = [row for row in review_rows if is_open(row)]
    canonical_open = [row for row in canonical_review_rows if is_open(row)]
    blocking: list[dict[str, Any]] = []
    advisory: list[dict[str, Any]] = []

    for row in open_rows:
        item: dict[str, Any] = {
            "review_id": row.get("review_id"),
            "object_id": row.get("object_id"),
            "source_ref": row.get("source_ref"),
            "raw_value": row.get("raw_value"),
            "issue_type": row.get("issue_type"),
            "candidate_match": row.get("candidate_match"),
        }
        if not is_advisory_low_confidence(row):
            item["reason"] = "open_non_advisory_review"
            blocking.append(item)
            continue

        person_id = row.get("source_ref", "").strip()
        refs = find_references(root, person_id) if person_id else []
        item["promoted_relationship_references"] = refs
        if refs:
            item["reason"] = "low_confidence_person_is_promoted_relationship_dependency"
            blocking.append(item)
        else:
            item["reason"] = "isolated_low_confidence_profile_advisory"
            advisory.append(item)

    canonical_graph_open = int(graph.get("review_queue_open") or 0)
    if canonical_open:
        blocking.append(
            {
                "reason": "canonical_review_queue_open",
                "count": len(canonical_open),
            }
        )
    if canonical_graph_open:
        blocking.append(
            {
                "reason": "canonical_graph_reports_open_review_queue",
                "count": canonical_graph_open,
            }
        )

    return {
        "schema_version": "moneysweep.entity_resolution_certification_audit/v2",
        "input_manifest": input_manifest,
        "open_entity_review_rows": len(open_rows),
        "advisory_low_confidence_rows": len(advisory),
        "blocking_review_items": len(blocking),
        "canonical_review_queue_open_rows": len(canonical_open),
        "canonical_graph_review_queue_open": canonical_graph_open,
        "g7_candidate_state": "PASS" if not blocking else "FAIL",
        "advisory": advisory,
        "blocking": blocking,
        "policy": {
            "name_only_resolution_allowed": False,
            "confidence_threshold_lowered": False,
            "advisory_rows_auto_closed": False,
            "promoted_low_confidence_dependency_blocks": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default="reports/entity_resolution_certification_audit.json")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    output = Path(args.output)
    if not output.is_absolute():
        output = root / output
    report = build(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "g7_candidate_state": report["g7_candidate_state"],
                "open_entity_review_rows": report["open_entity_review_rows"],
                "advisory_low_confidence_rows": report["advisory_low_confidence_rows"],
                "blocking_review_items": report["blocking_review_items"],
                "output": str(output),
            },
            indent=2,
        )
    )
    return 0 if report["g7_candidate_state"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
