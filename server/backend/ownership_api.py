from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, HTTPException

from moneysweep.capital_control.deep_dive import (
    OwnershipDeepDiveError,
    build_ownership_deep_dive,
    load_certification,
    load_materialized_holdings,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CERTIFICATION = (
    ROOT / "data" / "manifests" / "capital_control" / "bpop_sec13f_8q_certification.json"
)
DEFAULT_HOLDINGS = (
    ROOT / "data" / "staging" / "processed" / "capital_control" / "sec13f_pr_golden_holdings.csv"
)

router = APIRouter(prefix="/deep-dive/ownership", tags=["ownership-and-capital"])


def _paths() -> tuple[Path, Path]:
    certification = Path(
        os.environ.get("MONEYSWEEP_OWNERSHIP_CERTIFICATION", str(DEFAULT_CERTIFICATION))
    )
    holdings = Path(os.environ.get("MONEYSWEEP_OWNERSHIP_HOLDINGS", str(DEFAULT_HOLDINGS)))
    return certification, holdings


def _load() -> tuple[dict[str, object], tuple[dict[str, str], ...]]:
    certification_path, holdings_path = _paths()
    try:
        certification = load_certification(certification_path)
        holdings = load_materialized_holdings(holdings_path)
    except (OSError, ValueError, OwnershipDeepDiveError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return certification, holdings


@router.get("/status")
def ownership_status() -> dict[str, object]:
    certification_path, holdings_path = _paths()
    if not certification_path.is_file() or not holdings_path.is_file():
        return {
            "available": False,
            "certificationState": "NOT_MOUNTED",
            "certifiedIssuer": "BPOP",
            "providerEquivalence": "OPEN",
        }
    try:
        certification = load_certification(certification_path)
        holdings = load_materialized_holdings(holdings_path)
        view = build_ownership_deep_dive(
            holdings,
            certification,
            ticker="BPOP",
            cusip="733174700",
        )
    except (OSError, ValueError, OwnershipDeepDiveError) as exc:
        return {
            "available": False,
            "certificationState": "UNRESOLVED",
            "certifiedIssuer": "BPOP",
            "providerEquivalence": "OPEN",
            "blocker": str(exc),
        }
    # build_ownership_deep_dive() returns dict[str, object], so the nested
    # certification view needs an explicit cast before it can be indexed.
    certification_view = cast(Mapping[str, Any], view["certification"])
    return {
        "available": True,
        "certificationState": certification_view["state"],
        "certificationId": certification_view["certificationId"],
        "certifiedIssuer": "BPOP",
        "regressionIssuers": ["OFG", "EVTC"],
        "providerEquivalence": view["providerEquivalence"],
        "latestPeriod": view["latestPeriod"],
        "observationCount": view["observationCount"],
    }


@router.get("/{ticker}")
def ownership_deep_dive(ticker: str) -> dict[str, object]:
    requested = ticker.strip().upper()
    if requested in {"OFG", "EVTC"}:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{requested} is retained as a real-source regression issuer but does not inherit "
                "the bounded BPOP eight-quarter Deep Dive certification"
            ),
        )
    if requested != "BPOP":
        raise HTTPException(status_code=404, detail="no certified ownership Deep Dive for ticker")
    certification, holdings = _load()
    try:
        return build_ownership_deep_dive(
            holdings,
            certification,
            ticker="BPOP",
            cusip="733174700",
        )
    except OwnershipDeepDiveError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
