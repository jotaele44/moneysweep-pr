"""Add identity-safety gates to campaign-finance materialization validation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from scripts import validate_campaign_finance_materialization as legacy
from scripts.config import PROJECT_ROOT

CANDIDATE_STATUS = "CANDIDATE_NOT_IDENTITY"
VERIFIED_STATUS = "VERIFIED_ID"


def _read(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, dtype=str, low_memory=False).fillna("")
    except (OSError, UnicodeDecodeError, pd.errors.ParserError, pd.errors.EmptyDataError):
        return pd.DataFrame()


def identity_safety(root: Path) -> dict[str, Any]:
    processed = root / "data" / "staging" / "processed"
    blockers: list[str] = []
    metrics: dict[str, int] = {}

    candidates = _read(processed / "pr_campaign_finance_candidates.csv")
    committees = _read(processed / "pr_campaign_finance_committees.csv")
    recipients = _read(processed / "pr_campaign_finance_recipient_resolution.csv")
    edges = _read(processed / "pr_campaign_finance_edges.csv")

    def check_entity_frame(frame: pd.DataFrame, *, label: str, authority_col: str) -> None:
        if frame.empty:
            return
        if "identity_status" not in frame.columns:
            blockers.append(f"{label}:identity_status_missing")
            return
        authoritative = frame.get(authority_col, pd.Series("", index=frame.index)).astype(str).str.strip() != ""
        bad_verified = int((authoritative & (frame["identity_status"] != VERIFIED_STATUS)).sum())
        bad_unverified = int((~authoritative & (frame["identity_status"] != CANDIDATE_STATUS)).sum())
        bad_review = int(
            (
                ~authoritative
                & (frame.get("review_status", pd.Series("", index=frame.index)) != "needs_review")
            ).sum()
        )
        metrics[f"{label}_authoritative_ids"] = int(authoritative.sum())
        metrics[f"{label}_candidate_only"] = int((~authoritative).sum())
        if bad_verified:
            blockers.append(f"{label}:authoritative_id_not_marked_verified:{bad_verified}")
        if bad_unverified:
            blockers.append(f"{label}:idless_record_promoted:{bad_unverified}")
        if bad_review:
            blockers.append(f"{label}:idless_record_not_in_review:{bad_review}")

    check_entity_frame(candidates, label="candidates", authority_col="fec_candidate_id")
    check_entity_frame(committees, label="committees", authority_col="fec_committee_id")

    if not recipients.empty:
        required = {
            "resolved_entity_id",
            "resolved_entity_type",
            "match_method",
            "candidate_count",
            "candidate_entity_ids",
            "identity_status",
        }
        missing = sorted(required - set(recipients.columns))
        if missing:
            blockers.append("recipient_resolution:identity_fields_missing:" + ",".join(missing))
        else:
            name_only = recipients["match_method"].str.contains(
                "normalized_name", case=False, regex=False
            )
            resolved = recipients["resolved_entity_id"].astype(str).str.strip() != ""
            promoted = int((name_only & resolved).sum())
            metrics["recipient_name_only_candidates"] = int(name_only.sum())
            metrics["recipient_name_only_promotions"] = promoted
            if promoted:
                blockers.append(f"recipient_resolution:name_only_identity_promotion:{promoted}")
            bad_status = int(
                (
                    name_only
                    & ~recipients["identity_status"].isin([CANDIDATE_STATUS, "UNRESOLVED"])
                ).sum()
            )
            if bad_status:
                blockers.append(f"recipient_resolution:name_only_status_not_candidate:{bad_status}")

    if not edges.empty:
        required = {
            "identity_status",
            "source_identity_basis",
            "target_identity_basis",
            "source_entity_id",
            "target_entity_id",
        }
        missing = sorted(required - set(edges.columns))
        if missing:
            blockers.append("campaign_edges:identity_fields_missing:" + ",".join(missing))
        else:
            verified = edges["identity_status"] == VERIFIED_STATUS
            verified_bad_source = verified & ~edges["source_identity_basis"].isin(
                ["fec_committee_id", "fec_candidate_id"]
            )
            verified_bad_target = verified & ~edges["target_identity_basis"].isin(
                ["fec_committee_id", "fec_candidate_id"]
            )
            verified_blank_endpoint = verified & (
                (edges["source_entity_id"].astype(str).str.strip() == "")
                | (edges["target_entity_id"].astype(str).str.strip() == "")
            )
            name_only_verified = verified & (
                edges["source_identity_basis"].str.contains("normalized_name", case=False, regex=False)
                | edges["target_identity_basis"].str.contains("normalized_name", case=False, regex=False)
            )
            metrics["verified_identity_edges"] = int(verified.sum())
            metrics["candidate_identity_edges"] = int((~verified).sum())
            for label, mask in (
                ("verified_source_basis_invalid", verified_bad_source),
                ("verified_target_basis_invalid", verified_bad_target),
                ("verified_blank_endpoint", verified_blank_endpoint),
                ("name_only_verified_edge", name_only_verified),
            ):
                count = int(mask.sum())
                if count:
                    blockers.append(f"campaign_edges:{label}:{count}")

    return {
        "policy": "NO_NAME_ONLY_PROMOTION",
        "ok": not blockers,
        "blockers": sorted(set(blockers)),
        "metrics": dict(sorted(metrics.items())),
    }


def run(root: Path | None = None, *, strict: bool = False) -> dict[str, Any]:
    root = Path(root) if root is not None else PROJECT_ROOT
    report = legacy.run(root=root, strict=strict)
    safety = identity_safety(root)
    blocking = list(report.get("blocking", [])) + [
        f"identity_safety:{item}" for item in safety["blockers"]
    ]
    report["identity_safety"] = safety
    report["blocking"] = sorted(set(blocking))
    report["ok"] = not report["blocking"]
    path = root / "data" / "manifests" / "campaign_finance" / "campaign_finance_validation.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report["path"] = str(path)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()
    report = run(strict=args.strict)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["ok"] or args.report_only else 1


if __name__ == "__main__":
    raise SystemExit(main())
