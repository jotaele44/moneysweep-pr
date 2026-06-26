"""Resolve entity parent-UEI relationships and emit entities_resolved.csv.

Scans data/staging/processed/**/*.csv for every entity name + UEI,
cross-references vendor_uei_index.csv (SAM cache), and writes:
  data/staging/processed/entities_resolved.csv
  data/staging/processed/high_value_unresolved.csv
  data/staging/processed/parent_conflict_queue.csv

High-value threshold: $1,000,000 in total_obligation.

Usage:
  python3 scripts/parent_collapse.py
  python3 scripts/parent_collapse.py --root /path/to/repo
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moneysweep.runtime.alias_overrides import apply as apply_override
from moneysweep.runtime.alias_overrides import load_overrides
from moneysweep.runtime.name_normalization import normalize_name

NAME_FIELDS = [
    "recipient_name",
    "vendor_name",
    "award_recipient_name",
    "prime_recipient_name",
    "sub_recipient_name",
    "contractor",
    "applicant",
]

# Entity-type classification keyword sets (checked in priority order)
_AGGREGATE = frozenset(
    ["MULTIPLE RECIPIENTS", "VARIOUS RECIPIENTS", "ALL RECIPIENTS", "UNDISCLOSED"]
)
_GOVT = frozenset(
    [
        "DEPARTMENT OF",
        "DEPARTAMENTO DE",
        "DEPT OF",
        "ADMINISTRACION",
        "ADMINISTRACIÓN",
        "ADMINISTRATION OF",
        "AUTORIDAD",
        "AUTHORITY OF",
        "MUNICIPIO",
        "MUNICIPALITY OF",
        "MUNICIPALIDAD",
        "GOVERNMENT OF",
        "GOBIERNO DE",
        "GOVERNOR'S",
        "COMMONWEALTH OF",
        "ESTADO LIBRE ASOCIADO",
        "SECRETARIA",
        "SECRETARÍA",
        "SECRETARIAT",
        "JUNTA DE",
        "JUNTA OF",
        "OFICINA DE",
        "OFICINA DEL",
        "TRIBUNAL",
        "POLICIA",
        "POLICE DEPARTMENT",
        "HACIENDA",
        "CONSEJO DE",
        "DEPARTAMENTO",
        "AGENCIA",
    ]
)
_NONPROFIT = frozenset(
    [
        "UNIVERSITY",
        "UNIVERSIDAD",
        "COLLEGE",
        "ESCUELA GRADUADA",
        "FOUNDATION",
        "FUNDACION",
        "FUNDACIÓN",
        "IGLESIA",
        "CHURCH",
        "CATHEDRAL",
        "NONPROFIT",
        "NON-PROFIT",
        "COOPERATIVE",
        "COOPERATIVA",
    ]
)


def _classify_entity_type(name: str) -> str:
    """Return one of: aggregate, government, nonprofit, individual, corporate."""
    n = name.upper().strip()
    if not n:
        return "unknown"
    for pat in _AGGREGATE:
        if pat in n:
            return "aggregate"
    for kw in _GOVT:
        if kw in n:
            return "government"
    for kw in _NONPROFIT:
        if kw in n:
            return "nonprofit"
    # Heuristic: "SURNAME, FIRSTNAME [suffix]" pattern → individual
    if "," in n:
        parts = n.split(",", 1)
        left, right = parts[0].strip(), parts[1].strip()
        biz_suffixes = {"LLC", "INC", "CORP", "SA", "CSP", "LTD", "PSC", "CO", "S.A.", "SRL"}
        if (
            not any(s in right for s in biz_suffixes)
            and len(left.split()) <= 2
            and len(right.split()) <= 3
        ):
            return "individual"
    return "corporate"


UEI_FIELDS = ["recipient_uei", "uei", "entity_uei", "prime_uei", "sub_uei"]
PARENT_UEI_FIELDS = ["parent_uei", "ultimate_parent_uei", "immediate_parent_uei"]
PARENT_NAME_FIELDS = ["parent_name", "ultimate_parent_name", "immediate_parent_name"]
AMOUNT_FIELDS = [
    "obligated_amount",
    "total_obligation",
    "obligation_amount",
    "amount",
    "subaward_amount",
]
HIGH_VALUE_THRESHOLD = 1_000_000.0
_SKIP_FILENAMES = {
    "entities_resolved.csv",
    "high_value_unresolved.csv",
    "parent_conflict_queue.csv",
}


def _first(row: dict, fields: list[str]) -> str:
    for f in fields:
        v = row.get(f)
        if v not in (None, ""):
            return str(v).strip()
    return ""


def _money(row: dict) -> float:
    for f in AMOUNT_FIELDS:
        v = row.get(f)
        if v not in (None, ""):
            try:
                return float(str(v).replace(",", "").replace("$", ""))
            except Exception:
                pass
    return 0.0


def _read_csv(path: Path) -> list[dict]:
    if not path.exists() or path.stat().st_size == 0 or path.suffix.lower() != ".csv":
        return []
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _load_sam_index(root: Path) -> dict[str, dict]:
    idx: dict[str, dict] = {}
    candidates = [
        root / "data" / "staging" / "processed" / "enrichment" / "vendor_uei_index.csv",
        root / "data" / "staging" / "processed" / "sam_entities.csv",
        root / "data" / "staging" / "processed" / "entity_hierarchy.csv",
        root / "data" / "staging" / "processed" / "enrichment" / "usaspending_parent_index.csv",
    ]
    for p in candidates:
        for row in _read_csv(p):
            for key_val in [
                _first(row, NAME_FIELDS),
                row.get("normalized_name", ""),
                _first(row, UEI_FIELDS),
            ]:
                if not key_val:
                    continue
                lookup = normalize_name(key_val) if not str(key_val).isalnum() else str(key_val)
                if lookup:
                    idx[lookup] = row
    return idx


def build_entities(root: Path) -> dict[str, Any]:
    processed = root / "data" / "staging" / "processed"
    sam = _load_sam_index(root)
    overrides = load_overrides()
    ents: dict[str, dict] = {}
    conflicts: list[dict] = []

    for path in processed.rglob("*.csv") if processed.exists() else []:
        if path.name in _SKIP_FILENAMES:
            continue
        for row in _read_csv(path):
            raw_name = _first(row, NAME_FIELDS)
            uei = _first(row, UEI_FIELDS)
            norm, was_overridden = apply_override(
                raw_name or row.get("normalized_name", ""), overrides
            )
            if not norm and not uei:
                continue
            key = uei or norm
            e = ents.setdefault(
                key,
                {
                    "entity_id": key,
                    "normalized_name": norm,
                    "entity_name": raw_name,
                    "entity_uei": uei,
                    "entity_type": _classify_entity_type(raw_name or norm),
                    "parent_uei": "",
                    "parent_name": "",
                    "resolution_method": "alias_override" if was_overridden else "observed_only",
                    "match_confidence": 0.85 if was_overridden else 0.0,
                    "total_obligation": 0.0,
                    "record_count": 0,
                    "source_files": set(),
                },
            )
            if was_overridden and e["resolution_method"] == "observed_only":
                e["resolution_method"] = "alias_override"
                e["match_confidence"] = max(e["match_confidence"], 0.85)
            e["record_count"] += 1
            e["total_obligation"] += _money(row)
            e["source_files"].add(path.name)
            e["entity_name"] = e["entity_name"] or raw_name
            e["entity_uei"] = e["entity_uei"] or uei

            parent_uei = _first(row, PARENT_UEI_FIELDS)
            parent_name = _first(row, PARENT_NAME_FIELDS)
            sam_match = sam.get(uei) or sam.get(norm)

            if not parent_uei and not parent_name and sam_match:
                parent_uei = _first(sam_match, PARENT_UEI_FIELDS)
                parent_name = _first(sam_match, PARENT_NAME_FIELDS)
                e["entity_uei"] = e["entity_uei"] or _first(sam_match, UEI_FIELDS)

            if parent_uei or parent_name:
                if e["parent_uei"] and parent_uei and e["parent_uei"] != parent_uei:
                    conflicts.append(
                        {
                            "entity_id": key,
                            "entity_name": e["entity_name"],
                            "existing_parent_uei": e["parent_uei"],
                            "candidate_parent_uei": parent_uei,
                            "source_file": path.name,
                        }
                    )
                e["parent_uei"] = e["parent_uei"] or parent_uei
                e["parent_name"] = e["parent_name"] or parent_name
                e["resolution_method"] = "parent_field_or_sam_index"
                e["match_confidence"] = max(
                    float(e["match_confidence"]), 0.95 if parent_uei else 0.80
                )
            elif uei:
                e["resolution_method"] = "uei_no_parent"
                e["match_confidence"] = max(float(e["match_confidence"]), 0.70)

    rows = []
    for e in ents.values():
        e["manual_review_required"] = not bool(e["parent_uei"] or e["parent_name"])
        e["source_files"] = ";".join(sorted(e["source_files"]))
        e["total_obligation"] = round(e["total_obligation"], 2)
        rows.append(e)

    rows.sort(key=lambda r: (-r["total_obligation"], r["normalized_name"]))
    unresolved = [
        r
        for r in rows
        if r["manual_review_required"] and r["total_obligation"] >= HIGH_VALUE_THRESHOLD
    ]

    _write_csv(processed / "entities_resolved.csv", rows)
    _write_csv(processed / "high_value_unresolved.csv", unresolved)
    _write_csv(processed / "parent_conflict_queue.csv", conflicts)

    total = len(rows)
    resolved_count = sum(1 for r in rows if r["parent_uei"] or r["parent_name"])
    corporate = [r for r in rows if r.get("entity_type") == "corporate"]
    corp_resolved = sum(1 for r in corporate if r.get("parent_uei"))
    type_counts: dict = {}
    for r in rows:
        t = r.get("entity_type", "unknown")
        type_counts[t] = type_counts.get(t, 0) + 1
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "entity_count": total,
        "parent_resolved_count": resolved_count,
        "resolution_rate": (resolved_count / total) if total else 0.0,
        "high_value_unresolved_count": len(unresolved),
        "parent_conflict_count": len(conflicts),
        "entity_type_counts": type_counts,
        "corporate_entity_count": len(corporate),
        "corporate_parent_uei_rate": (corp_resolved / len(corporate)) if corporate else 0.0,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    a = p.parse_args(argv)
    print(json.dumps(build_entities(Path(a.root)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
