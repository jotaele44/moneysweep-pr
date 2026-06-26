"""Ingest the Top250 power registry into Canonical v1 ``people.csv`` (WS-D).

Policy (operator-approved):
* **Accept verified, queue the rest.** A person becomes an *accepted* node only
  when the registry both marks them ``confirmed=True`` **and** backs them with a
  Tier ``T1``/``T2`` evidence row. Everyone else (``confirmed=False`` or Tier
  ``T3``/``T4``) and any firm-embedded/ambiguous entry (e.g.
  ``"AlixPartners (Lisa Donahue)"``) is routed to a review queue as
  pending/unverified and is **never asserted**.
* **Commit verified only.** Accepted people + their evidence are written to the
  committed canonical tables. The pending/unverified review queue is written to
  a gitignored staging path so unverified named individuals are not published.

All claims are neutral (registry membership + thematic "flows" + evidence tier);
never accusatory, per ``docs/CLAIM_LANGUAGE_POLICY.md``. The raw scored registry
lives in the gitignored ``data/raw/`` zone.

Roadmap: WS-D, tasks T55-T68. Stdlib only.

CLI::

    python scripts/ingest_people.py            # build committed + pending tables
    python scripts/ingest_people.py --check     # summarize classification only
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moneysweep.runtime.canonical_ids import name_hash, person_id
from moneysweep.runtime.evidence_tiers import tier_confidence
from moneysweep.runtime.name_normalization import normalize_person_name
from scripts.build_evidence import Evidence, make_evidence, merge_evidence

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = "data/raw/top250_power_registry.csv"
SOURCE_NAME = "Top250 Power Registry"
PEOPLE_OUT = "data/canonical_v1/people.csv"
EVIDENCE_OUT = "data/canonical_v1/evidence.csv"
# Pending/unverified review items: gitignored (data/staging/processed/** is ignored).
PENDING_OUT = "data/staging/processed/canonical_v1/review_queue_people_pending.csv"
MANIFEST_OUT = "data/manifests/canonical_v1/people.json"

VERIFIED_TIERS = frozenset({"T1", "T2"})

PEOPLE_COLUMNS = [
    "person_id",
    "full_name",
    "normalized_name",
    "aliases",
    "primary_role",
    "primary_entity_id",
    "jurisdiction",
    "confidence",
    "evidence_id",
    "review_status",
    "notes",
]
REVIEW_COLUMNS = [
    "review_id",
    "object_type",
    "object_id",
    "issue_type",
    "raw_value",
    "candidate_match",
    "source_name",
    "source_ref",
    "severity",
    "recommended_action",
    "status",
]


def _truthy(value: str) -> bool:
    return str(value).strip().lower() in ("true", "1", "yes")


def _best_tier(tiers: list[str]) -> str:
    order = ["T1", "T2", "T3", "T4"]
    present = [t for t in order if t in tiers]
    return present[0] if present else "T4"


def _aggregate(path: Path) -> dict[str, dict[str, Any]]:
    """Collapse the registry to one record per person (keyed by normalized name)."""
    people: dict[str, dict[str, Any]] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for line_no, row in enumerate(csv.DictReader(fh), start=2):
            name = (row.get("name") or "").strip()
            if not name:
                continue
            key = normalize_person_name(name)
            etier = (row.get("evidence_tier") or "T4").strip()
            confirmed = _truthy(row.get("confirmed", ""))
            try:
                score = int(float(row.get("flow_score") or 0))
            except ValueError:
                score = 0
            rec = people.setdefault(
                key,
                {
                    "display_name": name,
                    "tiers": set(),
                    "flows": set(),
                    "evidence_tiers": [],
                    "max_score": -1,
                    "any_verified": False,
                    "ambiguous": False,
                    "first_line": line_no,
                    "display_names": set(),
                },
            )
            rec["display_names"].add(name)
            # prefer the highest-scoring spelling as the display name
            if score > rec["max_score"]:
                rec["display_name"] = name
                rec["max_score"] = max(rec["max_score"], score)
            rec["tiers"].add((row.get("tier") or "").strip())
            for flow in (row.get("flows") or "").replace(";", ",").split(","):
                flow = flow.strip()
                if flow:
                    rec["flows"].add(flow)
            rec["evidence_tiers"].append(etier)
            if "(" in name or ")" in name:
                rec["ambiguous"] = True
            if confirmed and etier in VERIFIED_TIERS:
                rec["any_verified"] = True
    return people


def _flows_str(rec: dict[str, Any]) -> str:
    return ",".join(sorted(rec["flows"]))


def _notes(rec: dict[str, Any]) -> str:
    tiers = "/".join(sorted(t for t in rec["tiers"] if t))
    return f"registry_tiers={tiers}; flows={_flows_str(rec)}; flow_score={rec['max_score']}"


def build_records(path: Path) -> dict[str, Any]:
    """Return classified records: people rows, evidence, pending review rows, counts."""
    people = _aggregate(path)
    people_rows: list[dict[str, Any]] = []
    evidence_rows: list[Evidence] = []
    pending_rows: list[dict[str, Any]] = []

    for key, rec in sorted(people.items()):
        name = rec["display_name"]
        pid = person_id(name)
        best_tier = _best_tier(rec["evidence_tiers"])
        verified = rec["any_verified"] and not rec["ambiguous"]

        if verified:
            ev = make_evidence(
                source_type="registry",
                source_name=SOURCE_NAME,
                source_path_or_url=SOURCE,
                page_or_line_ref=f"row {rec['first_line']}",
                claim=(
                    f"Registry lists '{name}' as a Puerto Rico public-money actor "
                    f"(tiers {'/'.join(sorted(t for t in rec['tiers'] if t))}; "
                    f"flows {_flows_str(rec)}); source-confirmed."
                ),
                extraction_method="manual",
                evidence_tier=best_tier,
                review_status="accepted",
            )
            evidence_rows.append(ev)
            people_rows.append(
                {
                    "person_id": pid,
                    "full_name": name,
                    "normalized_name": normalize_person_name(name),
                    "aliases": "|".join(sorted(n for n in rec["display_names"] if n != name)),
                    "primary_role": "",
                    "primary_entity_id": "",
                    "jurisdiction": "",
                    "confidence": tier_confidence(best_tier),
                    "evidence_id": ev.evidence_id,
                    "review_status": "accepted",
                    "notes": _notes(rec),
                }
            )
        else:
            if rec["ambiguous"]:
                issue, severity = "ambiguous", "high"
            elif rec["any_verified"] is False and best_tier in VERIFIED_TIERS:
                issue, severity = "unverified", "medium"  # confirmed=False but well-sourced tier
            elif best_tier in ("T3", "T4"):
                issue, severity = "low_confidence", "low"
            else:
                issue, severity = "unverified", "medium"
            pending_rows.append(
                {
                    "review_id": f"review_people_{name_hash(name, person=True)}",
                    "object_type": "Person",
                    "object_id": pid,
                    "issue_type": issue,
                    "raw_value": name,
                    "candidate_match": "",
                    "source_name": SOURCE_NAME,
                    "source_ref": f"row {rec['first_line']}",
                    "severity": severity,
                    "recommended_action": "verify against a primary source before promotion to people.csv",
                    "status": "open",
                }
            )

    # Light dedup/merge-candidate detection among accepted nodes (first+last token).
    pending_rows.extend(_merge_candidates(people_rows))

    return {
        "people_rows": people_rows,
        "evidence_rows": evidence_rows,
        "pending_rows": pending_rows,
        "counts": {
            "input_persons": len(people),
            "verified_accepted": len(people_rows),
            "pending_unverified": sum(
                1 for r in pending_rows if r["issue_type"] != "ambiguous_merge"
            ),
        },
    }


def _merge_candidates(people_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flag accepted nodes that may be the same person (shared first+last token)."""
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in people_rows:
        toks = row["normalized_name"].split()
        if len(toks) >= 2:
            buckets[(toks[0], toks[-1])].append(row)
    out: list[dict[str, Any]] = []
    for (_first, _last), rows in buckets.items():
        if len(rows) > 1:
            names = sorted(r["full_name"] for r in rows)
            for r in rows:
                others = [n for n in names if n != r["full_name"]]
                out.append(
                    {
                        "review_id": f"review_merge_{name_hash(r['full_name'], person=True)}",
                        "object_type": "Person",
                        "object_id": r["person_id"],
                        "issue_type": "ambiguous_merge",
                        "raw_value": r["full_name"],
                        "candidate_match": "|".join(others),
                        "source_name": SOURCE_NAME,
                        "source_ref": "",
                        "severity": "medium",
                        "recommended_action": "confirm whether these spellings are the same person; merge if so",
                        "status": "open",
                    }
                )
    return out


def _write_csv(rows: list[dict[str, Any]], columns: list[str], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def ingest(root: Path | None = None) -> dict[str, Any]:
    root = root or REPO_ROOT
    built = build_records(root / SOURCE)
    _write_csv(built["people_rows"], PEOPLE_COLUMNS, root / PEOPLE_OUT)
    evidence_manifest = merge_evidence(root / EVIDENCE_OUT, built["evidence_rows"])
    _write_csv(built["pending_rows"], REVIEW_COLUMNS, root / PENDING_OUT)

    manifest = {
        "producer_script": "scripts/ingest_people.py",
        "producer_phase": "CANONICAL_V1_PEOPLE_INGEST",
        "source_inputs": [SOURCE],
        "policy": "accept verified (confirmed + T1/T2); queue the rest; commit verified only",
        "committed_outputs": [PEOPLE_OUT, EVIDENCE_OUT],
        "gitignored_outputs": [PENDING_OUT],
        "counts": built["counts"],
        "evidence_table_rows": evidence_manifest["row_count"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = root / MANIFEST_OUT
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ingest Top250 power registry into canonical_v1 people."
    )
    parser.add_argument("--root", default=".")
    parser.add_argument(
        "--check", action="store_true", help="Summarize classification without writing."
    )
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()

    if args.check:
        built = build_records(root / SOURCE)
        print(json.dumps(built["counts"], indent=2))
        return 0

    print(json.dumps(ingest(root), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
