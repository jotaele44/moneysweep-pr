#!/usr/bin/env python3
"""Bounded public USAspending FY2026 PR award-location probe.

This preserves API bytes, does NOT assert completeness, program identity, or
equivalence of recipient geography and place-of-performance geography.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
FIELDS = [
    "Award ID",
    "Recipient Name",
    "Award Amount",
    "Recipient Location",
    "Primary Place of Performance",
]
SCOPES = {
    "recipient_pr": "recipient_locations",
    "performance_pr": "place_of_performance_locations",
}
MAX_RESPONSE_BYTES = 10 * 1024 * 1024
LIMIT = 25
PERIOD = [{"start_date": "2025-10-01", "end_date": "2026-09-30"}]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def request_body(scope: str) -> bytes:
    if scope not in SCOPES:
        raise ValueError("UNSUPPORTED_LOCATION_SCOPE")
    body = {
        "filters": {
            SCOPES[scope]: [{"country": "USA", "state": "PR"}],
            "time_period": PERIOD,
        },
        "fields": FIELDS,
        "sort": "Award Amount",
        "order": "desc",
        "limit": LIMIT,
        "page": 1,
        "spending_level": "awards",
        "subawards": False,
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def parse_page(data: bytes, expected_scope: str) -> dict:
    if expected_scope not in SCOPES:
        raise ValueError("SCOPE_INVALID")
    response = json.loads(data.decode("utf-8"))
    if not isinstance(response, dict):
        raise ValueError("API_RESPONSE_NOT_OBJECT")
    records = response.get("results")
    metadata = response.get("page_metadata")
    if not isinstance(records, list) or not isinstance(metadata, dict):
        raise ValueError("API_RESULTS_OR_METADATA_MISSING")
    if metadata.get("page") != 1 or not isinstance(metadata.get("hasNext"), bool):
        raise ValueError("API_PAGINATION_NOT_VERIFIABLE")
    if len(records) > LIMIT:
        raise ValueError("API_PAGE_LIMIT_EXCEEDED")
    if not records:
        raise ValueError("NO_ROWS_PROVES_NOTHING")
    identifiers = set()
    for row in records:
        if not isinstance(row, dict):
            raise ValueError("MALFORMED_AWARD_ROW")
        identifier = row.get("generated_internal_id")
        if identifier is None or str(identifier).strip() == "":
            raise ValueError("MISSING_AWARD_IDENTITY")
        if str(identifier) in identifiers:
            raise ValueError("DUPLICATE_AWARD_ON_PAGE")
        identifiers.add(str(identifier))
    return {
        "rows_observed": len(records),
        "unique_internal_awards": len(identifiers),
        "has_next": metadata["hasNext"],
        "last_page_confirmed": not metadata["hasNext"],
        "full_period_complete": False,
        "subaward_coverage_complete": False,
        "historical_coverage_complete": False,
        "public_program_identity_adjudicated": False,
    }


def fetch(scope: str, outdir: Path) -> dict:
    body = request_body(scope)
    request = Request(
        URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "PR-Program-Registry-Research-Probe/1.0",
        },
        method="POST",
    )
    response_path = outdir / f"{scope}_page1_raw.json"
    request_path = outdir / f"{scope}_request.json"
    request_path.write_bytes(body)
    with urlopen(request, timeout=60) as response:
        if response.geturl() != URL:
            raise ValueError("API_DESTINATION_DRIFT")
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    if not raw or len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("EMPTY_OR_OVERSIZED_RESPONSE")
    response_path.write_bytes(raw)
    parsed = parse_page(raw, scope)
    return {
        "request_sha256": sha256(body),
        "response_sha256": sha256(raw),
        "response_bytes": len(raw),
        "scope": scope,
        "request_file": request_path.name,
        "raw_file": response_path.name,
        **parsed,
    }


def main(output: Path) -> int:
    output.mkdir(parents=True, exist_ok=True)
    receipt = {
        "schema_version": "pr_registry_usaspending_bounded_probe_v1",
        "retrieval_utc": datetime.now(timezone.utc).isoformat(),
        "endpoint": URL,
        "time_period": PERIOD,
        "authority": "USAspending_API_v2",
        "evidence_class": "AWARD_LOCATION_DISCOVERY_NOT_CANONICAL_PR_PROGRAM",
        "scope": "FY2026_AWARDS_PAGE1_ONLY_NO_SUBAWARDS",
        "source_universe_complete": False,
        "pr_program_identity_complete": False,
        "certification": "WITHHELD",
        "results": {},
        "state": "BLOCKED",
    }
    for scope in SCOPES:
        try:
            receipt["results"][scope] = fetch(scope, output)
        except HTTPError as exc:
            error_body = exc.read(4096)
            receipt["results"][scope] = {
                "state": "FAILED",
                "error_class": "HTTPError",
                "http_status": exc.code,
                "error_response_sha256": sha256(error_body),
                "error_body_excerpt": error_body.decode("utf-8", errors="replace")[:2000],
            }
        except Exception as exc:
            receipt["results"][scope] = {
                "state": "FAILED",
                "error_class": type(exc).__name__,
                "error_message": str(exc)[:350],
            }
    passed = all(
        item.get("rows_observed", 0) > 0
        for item in receipt["results"].values()
    )
    receipt["state"] = (
        "BOUNDED_TWO_SCOPE_ACQUISITION_PASS" if passed else "BLOCKED_API_SCOPE"
    )
    (output / "usaspending_probe_receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if passed else 2


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("outputs/usaspending_pr_probe")
    raise SystemExit(main(target))
