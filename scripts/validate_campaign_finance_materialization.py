"""Validate campaign-finance data, derivations, and verified FEC acquisition accounting."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.campaign_finance_common import file_sha256
from scripts.config import PROJECT_ROOT

FILE_RULES: dict[str, dict[str, Any]] = {
    "fec_contributions": {
        "path": "data/staging/processed/pr_fec_contributions.csv",
        "required": True,
        "min_rows": 1,
        "columns": ["contributor_name", "contribution_receipt_amount", "committee_id"],
    },
    "fec_committees": {
        "path": "data/staging/processed/pr_fec_committees.csv",
        "required": True,
        "min_rows": 1,
        "columns": ["committee_id", "name"],
    },
    "fec_disbursements": {
        "path": "data/staging/processed/pr_fec_disbursements.csv",
        "required": True,
        "min_rows": 1,
        "columns": ["committee_id", "recipient_name", "disbursement_amount"],
    },
    "fec_independent_expenditures": {
        "path": "data/staging/processed/pr_fec_independent_expenditures.csv",
        "required": True,
        "min_rows": 0,
        "columns": ["committee_id", "candidate_id", "expenditure_amount"],
        "allow_header_only": True,
    },
    "cee_donations": {
        "path": "data/staging/processed/pr_donaciones.csv",
        "required": False,
        "min_rows": 1,
        "columns": ["donor_name", "amount", "candidate_or_committee"],
    },
    "oce_donations": {
        "path": "data/staging/processed/pr_oce_donations.csv",
        "required": True,
        "min_rows": 1,
        "columns": ["donor_name", "amount", "candidate_or_committee"],
    },
    "oce_reports": {
        "path": "data/staging/processed/pr_oce_reports.csv",
        "required": False,
        "min_rows": 0,
        "columns": ["committee_name", "report_number", "report_type"],
        "allow_header_only": True,
    },
    "candidates": {
        "path": "data/staging/processed/pr_campaign_finance_candidates.csv",
        "required": True,
        "min_rows": 1,
        "columns": ["candidate_entity_id", "canonical_name", "confidence"],
    },
    "committees": {
        "path": "data/staging/processed/pr_campaign_finance_committees.csv",
        "required": True,
        "min_rows": 1,
        "columns": ["committee_entity_id", "canonical_name", "confidence"],
    },
    "recipient_resolution": {
        "path": "data/staging/processed/pr_campaign_finance_recipient_resolution.csv",
        "required": True,
        "min_rows": 1,
        "columns": [
            "recipient_name",
            "identity_state",
            "candidate_set",
            "resolved_entity_id",
            "resolved_entity_type",
            "match_method",
            "review_status",
        ],
    },
    "campaign_edges": {
        "path": "data/staging/processed/pr_campaign_finance_edges.csv",
        "required": True,
        "min_rows": 0,
        "columns": [
            "edge_id",
            "source_entity_id",
            "edge_type",
            "target_entity_id",
            "source_dataset",
            "confidence",
        ],
        "allow_header_only": True,
    },
}

FEC_OUTFLOW_MANIFEST = "data/manifests/campaign_finance/fec_outflows_acquisition.json"

DERIVED_CONDITIONAL: dict[str, dict[str, Any]] = {
    "fec_awards_crossref": {
        "upstreams": [
            "data/staging/processed/pr_fec_contributions.csv",
            "data/staging/processed/pr_all_awards_master.csv",
        ],
        "path": "data/staging/processed/pr_fec_crossref.csv",
    },
    "ngo_donation_crossref": {
        "upstreams": [
            "data/staging/processed/ngos/ngos_master.csv",
            "data/staging/processed/pr_fec_contributions.csv",
        ],
        "path": "data/staging/processed/ngos/ngo_political_donations.csv",
    },
}


def _inspect_csv(path: Path, rule: dict) -> dict:
    result = {
        "path": str(path),
        "exists": path.exists(),
        "required": bool(rule.get("required")),
        "min_rows": int(rule.get("min_rows", 0)),
    }
    if not path.exists():
        result.update({"rows": 0, "columns": [], "sha256": "", "status": "missing"})
        return result
    try:
        df = pd.read_csv(path, dtype=str, low_memory=False)
    except Exception as exc:
        result.update(
            {
                "rows": 0,
                "columns": [],
                "sha256": file_sha256(path),
                "status": "unreadable",
                "error": str(exc),
            }
        )
        return result
    missing = [col for col in rule.get("columns", []) if col not in df.columns]
    rows = len(df)
    allow_header = bool(rule.get("allow_header_only"))
    if missing:
        status = "schema_error"
    elif rows < rule.get("min_rows", 0) and not (allow_header and rows == 0):
        status = "below_threshold"
    else:
        status = "ok"
    result.update(
        {
            "rows": rows,
            "columns": list(df.columns),
            "missing_columns": missing,
            "size_bytes": path.stat().st_size,
            "sha256": file_sha256(path),
            "status": status,
        }
    )
    return result


def run(root: Path | None = None, *, strict: bool = False) -> dict:
    root = Path(root) if root is not None else PROJECT_ROOT
    report_dir = root / "data" / "manifests" / "campaign_finance"
    report_dir.mkdir(parents=True, exist_ok=True)

    files = {name: _inspect_csv(root / rule["path"], rule) for name, rule in FILE_RULES.items()}
    blocking = [
        f"{name}:{info['status']}"
        for name, info in files.items()
        if info["required"] and info["status"] != "ok"
    ]

    outflow_manifest_path = root / FEC_OUTFLOW_MANIFEST
    outflow_acquisition: dict[str, Any] = {
        "path": str(outflow_manifest_path),
        "status": "missing",
    }
    if outflow_manifest_path.exists():
        try:
            payload = json.loads(outflow_manifest_path.read_text(encoding="utf-8"))
            schedule_b = payload.get("schedule_b", {})
            schedule_e = payload.get("schedule_e", {})
            complete = (
                payload.get("status") == "complete"
                and not schedule_b.get("skipped", False)
                and not schedule_e.get("skipped", False)
                and schedule_b.get("planned_batches") == schedule_b.get("completed_batches")
                and schedule_e.get("planned_cycles") == schedule_e.get("completed_cycles")
            )
            outflow_acquisition = {
                **payload,
                "path": str(outflow_manifest_path),
                "status": "ok" if complete else "incomplete",
            }
        except (OSError, ValueError, TypeError) as exc:
            outflow_acquisition = {
                "path": str(outflow_manifest_path),
                "status": "unreadable",
                "error": str(exc),
            }
    if outflow_acquisition["status"] != "ok":
        blocking.append(f"fec_outflow_acquisition:{outflow_acquisition['status']}")

    conditional = {}
    for name, rule in DERIVED_CONDITIONAL.items():
        upstream_ready = all((root / path).exists() for path in rule["upstreams"])
        output = root / rule["path"]
        output_ready = output.exists() and output.stat().st_size > 0
        status = (
            "not_applicable"
            if not upstream_ready
            else "ok"
            if output_ready
            else "missing_derived_output"
        )
        conditional[name] = {
            "upstream_ready": upstream_ready,
            "output": str(output),
            "output_ready": output_ready,
            "status": status,
        }
        if status == "missing_derived_output":
            blocking.append(f"{name}:{status}")

    pr_feed_rows = files["cee_donations"]["rows"] + files["oce_donations"]["rows"]
    if pr_feed_rows == 0:
        blocking.append("pr_donation_feeds:no_rows")

    recipient = files["recipient_resolution"]
    resolution_metrics: dict[str, int | float | None] = {
        "resolved": 0,
        "unresolved": 0,
        "candidate_not_identity": 0,
        "resolution_rate": None,
        "invalid_promotions": 0,
    }
    recipient_path = root / FILE_RULES["recipient_resolution"]["path"]
    if recipient_path.exists() and recipient["status"] == "ok":
        rdf = pd.read_csv(recipient_path, dtype=str, low_memory=False).fillna("")
        authoritative = (
            (rdf["identity_state"] == "AUTHORITATIVE_ID")
            & (rdf["match_method"] == "authoritative_recipient_id")
            & (rdf["resolved_entity_id"].str.strip() != "")
        )
        invalid_promotions = (
            (rdf["resolved_entity_id"].str.strip() != "")
            & ~authoritative
        )
        resolved = int(authoritative.sum())
        invalid_count = int(invalid_promotions.sum())
        unresolved = int((~authoritative).sum())
        candidate_only = int((rdf["identity_state"] == "CANDIDATE_NOT_IDENTITY").sum())
        total = resolved + unresolved
        resolution_metrics = {
            "resolved": resolved,
            "unresolved": unresolved,
            "candidate_not_identity": candidate_only,
            "resolution_rate": resolved / total if total else None,
            "invalid_promotions": invalid_count,
        }
        if invalid_count:
            blocking.append(
                f"recipient_resolution:unsupported_identity_promotion:{invalid_count}"
            )

    edges_path = root / FILE_RULES["campaign_edges"]["path"]
    edge_identity_metrics: dict[str, int] = {
        "rows": 0,
        "blank_endpoint_rows": 0,
        "duplicate_edge_ids": 0,
        "unknown_endpoint_rows": 0,
        "non_authoritative_source_rows": 0,
    }
    if edges_path.exists() and files["campaign_edges"]["status"] == "ok":
        edf = pd.read_csv(edges_path, dtype=str, low_memory=False).fillna("")
        edge_identity_metrics["rows"] = len(edf)
        blank_endpoints = (
            (edf["source_entity_id"].str.strip() == "")
            | (edf["target_entity_id"].str.strip() == "")
        )
        duplicate_edge_ids = edf["edge_id"].duplicated(keep=False)
        allowed_sources = {"fec_schedule_b", "fec_schedule_e"}
        non_authoritative_source = ~edf["source_dataset"].isin(allowed_sources)

        known_entity_ids: set[str] = set()
        for key, id_column in (
            ("candidates", "candidate_entity_id"),
            ("committees", "committee_entity_id"),
        ):
            entity_path = root / FILE_RULES[key]["path"]
            if entity_path.exists() and files[key]["status"] == "ok":
                entity_df = pd.read_csv(
                    entity_path,
                    dtype=str,
                    low_memory=False,
                ).fillna("")
                if id_column in entity_df:
                    known_entity_ids.update(
                        entity_df[id_column][
                            entity_df[id_column].str.strip() != ""
                        ].astype(str)
                    )

        unknown_endpoints = (
            ~edf["source_entity_id"].isin(known_entity_ids)
            | ~edf["target_entity_id"].isin(known_entity_ids)
        ) if len(edf) else pd.Series(dtype=bool)

        edge_identity_metrics.update(
            {
                "blank_endpoint_rows": int(blank_endpoints.sum()),
                "duplicate_edge_ids": int(duplicate_edge_ids.sum()),
                "unknown_endpoint_rows": int(unknown_endpoints.sum()),
                "non_authoritative_source_rows": int(
                    non_authoritative_source.sum()
                ),
            }
        )
        for key, count in edge_identity_metrics.items():
            if key != "rows" and count:
                blocking.append(f"campaign_edges:{key}:{count}")

    report = {
        "manifest_type": "campaign_finance_materialization_validation",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "strict": strict,
        "ok": not blocking,
        "blocking": blocking,
        "files": files,
        "fec_outflow_acquisition": outflow_acquisition,
        "conditional_derived_outputs": conditional,
        "metrics": {
            "federal_receipt_rows": files["fec_contributions"]["rows"],
            "federal_disbursement_rows": files["fec_disbursements"]["rows"],
            "federal_independent_expenditure_rows": files["fec_independent_expenditures"]["rows"],
            "pr_donation_rows": pr_feed_rows,
            "recipient_resolution": resolution_metrics,
            "edge_identity": edge_identity_metrics,
        },
    }
    path = report_dir / "campaign_finance_validation.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report["path"] = str(path)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Retained for compatibility; blocking-gate failure is the default exit behavior",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Write the report but exit 0 even on blocking failures (explicit advisory mode)",
    )
    args = parser.parse_args()
    report = run(strict=args.strict)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    # Fail closed by default: the source controller registers this script as
    # the materialization gate with no arguments, so a blocking failure must
    # not be recordable as a successful source update.
    return 0 if report["ok"] or args.report_only else 1


if __name__ == "__main__":
    raise SystemExit(main())
