#!/usr/bin/env python3
"""Read-only FY2022-FY2026 PR assistance award-class count evidence.

Counts are not award membership, canonical program identity, or PR program census.
Original API requests and responses are preserved before parsing.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ENDPOINT = "https://api.usaspending.gov/api/v2/search/spending_by_award_count/"
YEARS = tuple(range(2022, 2027))
LOCATIONS = {
    "recipient_pr": "recipient_locations",
    "performance_pr": "place_of_performance_locations",
}
# Officially accepted award-type filter values (not derived '-1').
CODES = ("02", "03", "04", "05", "06", "07", "08", "09", "10", "11")
GROUPS = ("grants", "loans", "direct_payments", "other")
MAX_BYTES = 1024 * 1024


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def request_bytes(year: int, location: str) -> bytes:
    if year not in YEARS or location not in LOCATIONS:
        raise ValueError("OUT_OF_SCOPE_QUERY")
    body = {
        "filters": {
            "award_type_codes": list(CODES),
            LOCATIONS[location]: [{"country": "USA", "state": "PR"}],
            "time_period": [
                {
                    "start_date": f"{year - 1}-10-01",
                    "end_date": f"{year}-09-30",
                }
            ],
        },
        "spending_level": "awards",
        "subawards": False,
    }
    return json.dumps(body, separators=(",", ":"), sort_keys=True).encode()


def parse_count(data: bytes) -> dict[str, int]:
    response = json.loads(data)
    if not isinstance(response, dict) or response.get("spending_level") != "awards":
        raise ValueError("INVALID_SPENDING_LEVEL")
    result = response.get("results")
    if not isinstance(result, dict):
        raise ValueError("MISSING_COUNT_RESULTS")
    parsed = {}
    for group in GROUPS:
        n = result.get(group)
        if type(n) is not int or n < 0:
            raise ValueError(f"INVALID_COUNT_{group}")
        parsed[group] = n
    for group in ("contracts", "idvs"):
        if type(result.get(group)) is not int or result[group] != 0:
            raise ValueError(f"NON_ASSISTANCE_LEAKAGE_{group}")
    return parsed


def acquire(target: Path) -> int:
    target.mkdir(parents=True, exist_ok=True)
    receipt: dict[str, Any] = {
        "schema_version": "pr_registry_assistance_class_counts_v1",
        "retrieved_utc": datetime.now(timezone.utc).isoformat(),
        "endpoint": ENDPOINT,
        "years": list(YEARS),
        "locations": list(LOCATIONS),
        "award_type_codes": list(CODES),
        "results": {},
        "status": "BLOCKED",
        "all_fiscal_years_complete": False,
        "unknown_type_awards_complete": False,
        "subaward_membership_complete": False,
        "award_membership_complete": False,
        "canonical_public_program_count": None,
        "registry_certification": "WITHHELD",
    }
    for year in YEARS:
        for location in LOCATIONS:
            label = f"fy{year}_{location}"
            body = request_bytes(year, location)
            (target / f"{label}_request.json").write_bytes(body)
            try:
                request = Request(
                    ENDPOINT,
                    data=body,
                    method="POST",
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": "PR-Program-Registry-Count-Evidence/1.0",
                    },
                )
                with urlopen(request, timeout=60) as response:
                    if response.geturl() != ENDPOINT:
                        raise ValueError("SOURCE_ENDPOINT_DRIFT")
                    data = response.read(MAX_BYTES + 1)
                if not data or len(data) > MAX_BYTES:
                    raise ValueError("INVALID_RESPONSE_SIZE")
                (target / f"{label}_response.json").write_bytes(data)
                receipt["results"][label] = {
                    "state": "COUNT_OBSERVED",
                    "counts": parse_count(data),
                    "request_sha256": digest(body),
                    "response_sha256": digest(data),
                    "response_bytes": len(data),
                    "membership_reconciled": False,
                }
            except Exception as error:
                message = str(error)
                if isinstance(error, HTTPError):
                    message = error.read(4096).decode("utf-8", "replace")
                receipt["results"][label] = {
                    "state": "BLOCKED",
                    "error_type": type(error).__name__,
                    "error_message": message[:1000],
                }
    if len(receipt["results"]) == len(YEARS) * len(LOCATIONS) and all(
        x["state"] == "COUNT_OBSERVED" for x in receipt["results"].values()
    ):
        receipt["status"] = "BOUNDED_CLASS_COUNT_OBSERVATIONS_PASS"
    (target / "count_receipt.json").write_text(
        json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "scopes": {
                    key: val.get("counts", val.get("error_type"))
                    for key, val in receipt["results"].items()
                },
            },
            sort_keys=True,
            indent=2,
        )
    )
    return 0 if receipt["status"] == "BOUNDED_CLASS_COUNT_OBSERVATIONS_PASS" else 2


if __name__ == "__main__":
    output = (
        Path(sys.argv[1]) if len(sys.argv) > 1 else Path("outputs/pr_registry_fy2022_2026_counts")
    )
    raise SystemExit(acquire(output))
