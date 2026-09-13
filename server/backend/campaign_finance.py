"""Read-only FastAPI routes for MoneySweep campaign-finance datasets."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pandas as pd
from fastapi import APIRouter, Query
from pandas.errors import EmptyDataError

ROOT = Path(__file__).resolve().parents[2]
PROCESSED = ROOT / "data" / "staging" / "processed"

router = APIRouter(tags=["campaign-finance"])

FILES = {
    "fec": "pr_fec_contributions.csv",
    "cee": "pr_donaciones.csv",
    "oce": "pr_oce_donations.csv",
    "reports": "pr_oce_reports.csv",
    "candidates": "pr_campaign_finance_candidates.csv",
    "committees": "pr_campaign_finance_committees.csv",
    "recipients": "pr_campaign_finance_recipient_resolution.csv",
    "edges": "pr_campaign_finance_edges.csv",
    "fec_committees": "pr_fec_committees.csv",
    "fec_disbursements": "pr_fec_disbursements.csv",
    "fec_expenditures": "pr_fec_independent_expenditures.csv",
}

_CACHE: dict[Path, tuple[float, pd.DataFrame]] = {}


def _data(key: str) -> pd.DataFrame:
    path = PROCESSED / FILES[key]
    if not path.exists():
        return pd.DataFrame()
    mtime = path.stat().st_mtime
    cached = _CACHE.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        frame = pd.read_csv(path, dtype=str, low_memory=False).fillna("")
    except EmptyDataError:
        frame = pd.DataFrame()
    _CACHE[path] = (mtime, frame)
    return frame


def _series(frame: pd.DataFrame, column: str, default: str = "") -> pd.Series:
    if column in frame.columns:
        return frame[column].fillna("")
    return pd.Series(default, index=frame.index, dtype="object")


def _amount(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.astype(str).str.replace("$", "", regex=False).str.replace(",", "", regex=False),
        errors="coerce",
    ).fillna(0)


def _summary(key: str, amount_col: str | None, date_col: str | None) -> dict:
    frame = _data(key)
    path = PROCESSED / FILES[key]
    present = path.exists()
    result = {
        "source": key,
        "file": FILES[key],
        "present": present,
        "status": "available" if len(frame) else "empty" if present else "unavailable",
        "rows": int(len(frame)),
        "amount": None,
        "earliest": None,
        "latest": None,
        "updatedAt": (
            datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat() if present else None
        ),
    }
    if not frame.empty and amount_col and amount_col in frame.columns:
        result["amount"] = float(_amount(frame[amount_col]).sum())
    if not frame.empty and date_col and date_col in frame.columns:
        dates = pd.to_datetime(frame[date_col], errors="coerce").dropna()
        if not dates.empty:
            result["earliest"] = dates.min().strftime("%Y-%m-%d")
            result["latest"] = dates.max().strftime("%Y-%m-%d")
    return result


def _finite(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


@router.get("/campaign-finance/summary")
def campaign_finance_summary():
    sources = [
        _summary("fec", "contribution_receipt_amount", "contribution_receipt_date"),
        _summary("cee", "amount", "contribution_date"),
        _summary("oce", "amount", "contribution_date"),
        _summary("fec_disbursements", "disbursement_amount", "disbursement_date"),
        _summary("fec_expenditures", "expenditure_amount", "expenditure_date"),
    ]
    derived = {
        key: int(len(_data(key)))
        for key in ("candidates", "committees", "recipients", "edges", "reports")
    }
    present_files = [
        PROCESSED / filename for filename in FILES.values() if (PROCESSED / filename).exists()
    ]
    has_data = any(source["rows"] for source in sources) or any(derived.values())
    return {
        "sources": sources,
        "totalContributionRows": sum(s["rows"] for s in sources[:3]),
        "totalContributionAmount": sum(s["amount"] or 0 for s in sources[:3]),
        "totalFederalOutflowRows": sources[3]["rows"] + sources[4]["rows"],
        "derived": derived,
        "hasData": bool(has_data),
        "materializedFileCount": len(present_files),
        "updatedAt": (
            datetime.fromtimestamp(
                max(path.stat().st_mtime for path in present_files), tz=UTC
            ).isoformat()
            if present_files
            else None
        ),
        "emptyState": (
            None
            if has_data
            else "No campaign-finance datasets are materialized in this repository checkout."
        ),
    }


def _standardize_contributions(source: str) -> pd.DataFrame:
    frame = _data(source)
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "source",
                "donorName",
                "amount",
                "date",
                "recipientName",
                "party",
                "cycle",
                "donorType",
                "committeeId",
                "candidateId",
            ]
        )
    if source == "fec":
        out = pd.DataFrame(
            {
                "source": "fec",
                "donorName": _series(frame, "contributor_name"),
                "amount": _amount(_series(frame, "contribution_receipt_amount")),
                "date": _series(frame, "contribution_receipt_date"),
                "recipientName": _series(frame, "committee_name"),
                "party": "",
                "cycle": _series(frame, "cycle"),
                "donorType": _series(frame, "is_individual")
                .astype(str)
                .str.lower()
                .map({"true": "individual", "false": "organization"})
                .fillna("unknown"),
                "committeeId": _series(frame, "committee_id"),
                "candidateId": _series(frame, "candidate_id"),
            }
        )
    else:
        out = pd.DataFrame(
            {
                "source": source,
                "donorName": _series(frame, "donor_name"),
                "amount": _amount(_series(frame, "amount")),
                "date": _series(frame, "contribution_date"),
                "recipientName": _series(frame, "candidate_or_committee"),
                "party": _series(frame, "party"),
                "cycle": _series(frame, "cycle"),
                "donorType": "unknown",
                "committeeId": "",
                "candidateId": "",
            }
        )
    return out


@router.get("/campaign-finance/contributions")
def campaign_finance_contributions(
    source: Literal["all", "fec", "cee", "oce"] = "all",
    q: str | None = None,
    recipient: str | None = None,
    party: str | None = None,
    cycle: str | None = None,
    donor_type: str | None = None,
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
):
    selected = ["fec", "cee", "oce"] if source == "all" else [source]
    frame = pd.concat([_standardize_contributions(key) for key in selected], ignore_index=True)
    if q:
        frame = frame[frame["donorName"].astype(str).str.contains(q, case=False, na=False)]
    if recipient:
        frame = frame[
            frame["recipientName"].astype(str).str.contains(recipient, case=False, na=False)
        ]
    if party:
        frame = frame[frame["party"].astype(str).str.contains(party, case=False, na=False)]
    if cycle:
        frame = frame[frame["cycle"].astype(str) == str(cycle)]
    if donor_type:
        frame = frame[frame["donorType"].astype(str) == donor_type]
    frame = frame.sort_values("date", ascending=False, kind="stable")
    total = len(frame)
    page = frame.iloc[offset : offset + limit]
    records = page.to_dict("records")
    for record in records:
        record["amount"] = _finite(record.get("amount"))
    return {"rows": records, "total": total, "limit": limit, "offset": offset}


@router.get("/campaign-finance/entities")
def campaign_finance_entities(
    entity_type: Literal["all", "candidate", "committee", "recipient"] = "all",
    q: str | None = None,
    limit: int = Query(1000, ge=1, le=5000),
):
    rows: list[dict] = []
    if entity_type in {"all", "candidate"}:
        for _, row in _data("candidates").iterrows():
            rows.append(
                {
                    "entityType": "candidate",
                    "entityId": row.get("candidate_entity_id"),
                    "name": row.get("canonical_name"),
                    "party": row.get("party"),
                    "office": row.get("office_sought"),
                    "confidence": _finite(row.get("confidence")),
                    "reviewStatus": row.get("review_status"),
                }
            )
    if entity_type in {"all", "committee"}:
        for _, row in _data("committees").iterrows():
            rows.append(
                {
                    "entityType": "committee",
                    "entityId": row.get("committee_entity_id"),
                    "name": row.get("canonical_name"),
                    "party": row.get("party"),
                    "office": row.get("committee_type"),
                    "confidence": _finite(row.get("confidence")),
                    "reviewStatus": row.get("review_status"),
                }
            )
    if entity_type in {"all", "recipient"}:
        for _, row in _data("recipients").iterrows():
            rows.append(
                {
                    "entityType": "recipient",
                    "entityId": row.get("resolved_entity_id") or row.get("recipient_resolution_id"),
                    "name": row.get("recipient_name"),
                    "resolvedType": row.get("resolved_entity_type"),
                    "amount": _finite(row.get("total_disbursements")),
                    "confidence": _finite(row.get("confidence")),
                    "reviewStatus": row.get("review_status"),
                }
            )
    if q:
        rows = [row for row in rows if q.lower() in str(row.get("name") or "").lower()]
    return rows[:limit]


@router.get("/campaign-finance/reports")
def campaign_finance_reports(q: str | None = None, limit: int = Query(1000, ge=1, le=5000)):
    frame = _data("reports")
    if q and not frame.empty:
        mask = _series(frame, "committee_name").astype(str).str.contains(q, case=False, na=False)
        frame = frame[mask]
    return frame.head(limit).to_dict("records") if not frame.empty else []
