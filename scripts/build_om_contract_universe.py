#!/usr/bin/env python3
"""Build a fail-closed Puerto Rico O&M contract universe from materialized sources.

This command never claims completeness. It classifies available contract rows,
deduplicates exact/source-overlap records, emits coverage matrices, and writes an
explicit blocker ledger consumed by ``validate_om_contract_universe.py``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
TAXONOMY = ROOT / "registries/om_contract_taxonomy.yaml"
OUT_DIR = ROOT / "reports/om_contract_universe"

SOURCE_FILES = {
    "ocpr_contracts": "data/staging/processed/pr_ocpr_contracts.csv",
    "asg_emergency_purchases": "data/staging/processed/pr_asg_emergency_purchases.csv",
    "compras_pr": "data/staging/processed/pr_compras_awards.csv",
    "cor3": "data/staging/processed/pr_cor3_projects.csv",
    "usaspending_prime": "data/staging/processed/pr_contracts_master.csv",
    "usaspending_subawards": "data/staging/processed/pr_subawards_master.csv",
    "prasa": "data/staging/processed/pr_prasa_contracts.csv",
    "prepa_luma_genera": "data/staging/processed/pr_prepa_contracts.csv",
    "dtop_road_contracts": "data/staging/processed/pr_dtop_road_contracts.csv",
    "transit_contracts": "data/staging/processed/pr_transit_contracts.csv",
    "ports_airports_contracts": "data/staging/processed/pr_ports_airports_contracts.csv",
    "p3_authority": "data/staging/processed/pr_p3_contracts.csv",
}

ALIASES = {
    "contract_number": ["contract_number", "contract_id", "award_id", "numero_contrato"],
    "contractor_name": ["contractor_name", "recipient_name", "vendor_name", "contratista"],
    "agency": ["agency", "awarding_agency_name", "entity_name", "agencia"],
    "municipality": ["municipality", "municipio", "place_of_performance_city_name"],
    "contract_amount": ["contract_amount", "award_amount", "amount", "obligation"],
    "start_date": ["start_date", "award_date", "date_signed", "fecha_inicio"],
    "end_date": ["end_date", "period_of_performance_end_date", "fecha_fin"],
    "service_description": ["service_description", "description", "award_description", "purpose"],
    "contract_type": ["contract_type", "award_type", "service_group", "type"],
    "status": ["status", "contract_status"],
    "document_url": ["document_url", "source_url", "url"],
}


def norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text)).strip()


def first_column(frame: pd.DataFrame, candidates: list[str]) -> pd.Series:
    for name in candidates:
        if name in frame.columns:
            return frame[name].fillna("").astype(str)
    return pd.Series([""] * len(frame), index=frame.index, dtype="string")


def canonicalize(frame: pd.DataFrame, source_id: str) -> pd.DataFrame:
    out = pd.DataFrame(index=frame.index)
    for target, candidates in ALIASES.items():
        out[target] = first_column(frame, candidates)
    out["source_id"] = source_id
    out["source_row"] = frame.index.astype(int) + 2
    out["source_present"] = True
    return out


def load_taxonomy(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "om_contract_taxonomy_v1":
        raise ValueError("Unsupported O&M taxonomy schema")
    return payload


def classify(row: pd.Series, taxonomy: dict) -> tuple[str, str, int, str]:
    evidence = " ".join(
        norm(row.get(field, "")) for field in taxonomy["classification_policy"]["evidence_fields"]
    )
    negatives = [term for term in taxonomy.get("negative_terms", []) if norm(term) in evidence]
    matches: list[tuple[str, str]] = []
    for category, spec in taxonomy["categories"].items():
        for term in spec.get("terms", []):
            if norm(term) in evidence:
                matches.append((category, term))
                break
    score = len(matches)
    policy = taxonomy["classification_policy"]
    if score >= int(policy["minimum_positive_score"]):
        classification = policy["positive_class"]
    elif score >= int(policy["minimum_review_score"]):
        classification = policy["review_class"]
    else:
        classification = policy["default_class"]
    if negatives and score <= 1 and policy.get("negative_terms_override_single_positive", True):
        classification = policy["default_class"]
    categories = ";".join(sorted({category for category, _ in matches}))
    terms = ";".join(sorted({term for _, term in matches}))
    return classification, categories, score, terms


def fingerprint(row: pd.Series) -> str:
    parts = [
        norm(row.get("contract_number")),
        norm(row.get("contractor_name")),
        norm(row.get("agency")),
        norm(row.get("contract_amount")),
        norm(row.get("start_date")),
        norm(row.get("service_description"))[:240],
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def materialization_status(root: Path) -> pd.DataFrame:
    rows = []
    for source_id, relative in SOURCE_FILES.items():
        path = root / relative
        status = "missing"
        row_count = 0
        if path.exists():
            try:
                with path.open(encoding="utf-8", errors="replace") as source_file:
                    row_count = max(sum(1 for _ in source_file) - 1, 0)
                status = "materialized" if row_count else "empty"
            except OSError:
                status = "unreadable"
        rows.append(
            {"source_id": source_id, "path": relative, "status": status, "row_count": row_count}
        )
    return pd.DataFrame(rows)


def run(root: Path = ROOT, out_dir: Path = OUT_DIR) -> dict:
    taxonomy = load_taxonomy(root / TAXONOMY.relative_to(ROOT))
    out_dir.mkdir(parents=True, exist_ok=True)
    status = materialization_status(root)
    status.to_csv(out_dir / "source_materialization.csv", index=False)

    frames = []
    for item in status.to_dict("records"):
        if item["status"] != "materialized":
            continue
        path = root / item["path"]
        try:
            frames.append(
                canonicalize(pd.read_csv(path, dtype=str, keep_default_na=False), item["source_id"])
            )
        except Exception as exc:
            status.loc[status.source_id == item["source_id"], "status"] = (
                f"read_error:{type(exc).__name__}"
            )
    status.to_csv(out_dir / "source_materialization.csv", index=False)

    universe = (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(columns=list(ALIASES) + ["source_id", "source_row", "source_present"])
    )
    if not universe.empty:
        results = universe.apply(lambda row: classify(row, taxonomy), axis=1, result_type="expand")
        results.columns = ["om_classification", "om_categories", "om_score", "om_match_terms"]
        universe = pd.concat([universe, results], axis=1)
        universe["dedup_fingerprint"] = universe.apply(fingerprint, axis=1)
        universe["duplicate_count"] = universe.groupby("dedup_fingerprint")[
            "dedup_fingerprint"
        ].transform("size")
        universe["dedup_status"] = universe["duplicate_count"].map(
            lambda n: "duplicate_review" if n > 1 else "unique"
        )
    universe.to_csv(out_dir / "om_contract_universe.csv", index=False)

    om = universe[
        universe.get("om_classification", pd.Series(dtype=str)).isin(["om", "om_review"])
    ].copy()
    dimensions = {
        "agency": "coverage_by_agency.csv",
        "municipality": "coverage_by_municipality.csv",
        "start_date": "coverage_by_fiscal_year.csv",
        "om_categories": "coverage_by_category.csv",
        "contractor_name": "coverage_by_contractor.csv",
        "source_id": "coverage_by_source.csv",
    }
    for column, filename in dimensions.items():
        if column not in om.columns or om.empty:
            pd.DataFrame(columns=[column, "record_count", "contract_amount_numeric"]).to_csv(
                out_dir / filename, index=False
            )
            continue
        work = om.copy()
        if column == "start_date":
            work["fiscal_year"] = pd.to_datetime(work[column], errors="coerce").dt.year
            group_column = "fiscal_year"
        else:
            group_column = column
        work["contract_amount_numeric"] = pd.to_numeric(
            work["contract_amount"].str.replace(r"[^0-9.\-]", "", regex=True), errors="coerce"
        )
        matrix = (
            work.groupby(group_column, dropna=False)
            .agg(
                record_count=("source_id", "size"),
                contract_amount_numeric=("contract_amount_numeric", "sum"),
            )
            .reset_index()
        )
        matrix.to_csv(out_dir / filename, index=False)

    blockers = []
    for item in status.to_dict("records"):
        if item["status"] != "materialized":
            blockers.append(
                {
                    "blocker_id": f"SOURCE_{item['source_id'].upper()}",
                    "severity": "blocking",
                    "detail": f"{item['source_id']} is {item['status']}",
                }
            )
    if not universe.empty and (universe.get("dedup_status") == "duplicate_review").any():
        blockers.append(
            {
                "blocker_id": "UNEXPLAINED_DUPLICATES",
                "severity": "blocking",
                "detail": "One or more cross-source fingerprints require adjudication",
            }
        )
    blockers.extend(
        [
            {
                "blocker_id": "MUNICIPALITY_78_ACCOUNTING",
                "severity": "blocking",
                "detail": "78-municipality accounting has not yet been certified",
            },
            {
                "blocker_id": "PUBLIC_CORPORATION_ACCOUNTING",
                "severity": "blocking",
                "detail": "Public-corporation universe has not yet been certified",
            },
            {
                "blocker_id": "OCPR_FULL_MATERIALIZATION",
                "severity": "blocking",
                "detail": "OCPR full-registry completion receipt is required",
            },
        ]
    )
    pd.DataFrame(blockers).drop_duplicates(subset=["blocker_id"]).to_csv(
        out_dir / "unresolved_gap_ledger.csv", index=False
    )

    summary = {
        "schema_version": "om_contract_universe_summary_v1",
        "status": "NON_PRODUCTION_DIAGNOSTIC",
        "complete_claim_allowed": False,
        "source_count": int(len(status)),
        "materialized_source_count": int((status.status == "materialized").sum()),
        "input_rows": int(len(universe)),
        "om_rows": int((universe.get("om_classification", pd.Series(dtype=str)) == "om").sum()),
        "om_review_rows": int(
            (universe.get("om_classification", pd.Series(dtype=str)) == "om_review").sum()
        ),
        "blocking_items": int(len(pd.DataFrame(blockers).drop_duplicates(subset=["blocker_id"]))),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = parser.parse_args()
    summary = run(args.root.resolve(), args.out_dir.resolve())
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
