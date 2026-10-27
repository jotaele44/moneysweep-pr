#!/usr/bin/env python3
"""Read-only USAspending FY2026 PR grant count cross-check; no certification."""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

API = "https://api.usaspending.gov/api/v2/search/spending_by_award_count/"
TYPES = ("02", "03", "04", "05")
PERIOD = {"start_date": "2025-10-01", "end_date": "2026-09-30"}
SCOPES = {"recipient_pr": "recipient_locations",
          "performance_pr": "place_of_performance_locations"}
MAX_BYTES = 1024 * 1024


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def request_bytes(scope: str) -> bytes:
    if scope not in SCOPES:
        raise ValueError("UNKNOWN_LOCATION_SCOPE")
    query = {
        "filters": {
            SCOPES[scope]: [{"country": "USA", "state": "PR"}],
            "time_period": [PERIOD],
            "award_type_codes": list(TYPES),
        },
        "spending_level": "awards",
        "subawards": False,
    }
    return json.dumps(query, sort_keys=True, separators=(",", ":")).encode()


def parse_count(data: bytes) -> int:
    obj = json.loads(data)
    if not isinstance(obj, dict) or not isinstance(obj.get("results"), dict):
        raise ValueError("COUNT_RESPONSE_MALFORMED")
    result = obj["results"]
    if obj.get("spending_level") != "awards":
        raise ValueError("WRONG_SPENDING_LEVEL")
    n = result.get("grants")
    if type(n) is not int or n < 0:
        raise ValueError("GRANT_COUNT_INVALID")
    return n


def run(target: Path) -> int:
    target.mkdir(parents=True, exist_ok=True)
    receipt: dict[str, Any] = {
        "schema_version": "pr_registry_usaspending_fy2026_count_v1",
        "retrieved_utc": datetime.now(timezone.utc).isoformat(),
        "endpoint": API,
        "period": PERIOD,
        "grant_types": list(TYPES),
        "status": "BLOCKED",
        "federal_program_universe_complete": False,
        "fy2026_award_membership_complete": False,
        "independently_verified_count": False,
        "subawards_included": False,
        "historical_fiscal_years_complete": False,
        "canonical_identity_certified": False,
        "certification": "WITHHELD",
        "scopes": {},
    }
    for label in SCOPES:
        body = request_bytes(label)
        (target / f"{label}_request.json").write_bytes(body)
        try:
            req = Request(API, data=body, method="POST", headers={
                "Content-Type": "application/json",
                "User-Agent": "PR-Registry-ReadOnly-Denominator/1.0",
            })
            with urlopen(req, timeout=60) as r:
                if r.geturl() != API:
                    raise ValueError("ENDPOINT_DRIFT")
                content = r.read(MAX_BYTES + 1)
            if not content or len(content) > MAX_BYTES:
                raise ValueError("COUNT_RESPONSE_SIZE_INVALID")
            (target / f"{label}_response_raw.json").write_bytes(content)
            count = parse_count(content)
            receipt["scopes"][label] = {
                "status": "BOUNDED_COUNT_OBSERVED",
                "grant_count": count,
                "request_sha256": digest(body),
                "response_sha256": digest(content),
                "response_bytes": len(content),
                "pagination_exhausted": False,
                "source_independent": False,
            }
        except Exception as err:
            message = str(err)
            if isinstance(err, HTTPError):
                message = err.read(4096).decode("utf-8", "replace")
            receipt["scopes"][label] = {
                "status": "BLOCKED",
                "error_type": type(err).__name__,
                "detail": message[:1000],
            }
    if all(d.get("status") == "BOUNDED_COUNT_OBSERVED"
           for d in receipt["scopes"].values()):
        receipt["status"] = "TWO_GEO_COUNTS_OBSERVED"
    (target / "count_receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt["status"] == "TWO_GEO_COUNTS_OBSERVED" else 2


if __name__ == "__main__":
    raise SystemExit(run(Path(sys.argv[1]) if len(sys.argv) > 1 else
                         Path("outputs/pr_registry_fy2026_counts")))
