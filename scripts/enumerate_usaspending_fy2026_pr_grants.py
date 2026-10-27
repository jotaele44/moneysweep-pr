#!/usr/bin/env python3
"""Bounded exact FY2026 Puerto Rico grant-award identity enumeration.

Fail closed on silent pagination truncation, duplicate or missing internal IDs,
response/denominator drift, geography mismatch, and terminal-page ambiguity.
SCOPE: grants 02/03/04/05, FY2026, prime awards, recipient OR performance PR.
This is not all financial awards, all historical years, or all public programs.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
COUNT_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award_count/"
PERIOD = {"start_date": "2025-10-01", "end_date": "2026-09-30"}
CODES = ["02", "03", "04", "05"]
SCOPES = {
    "recipient_pr": ("recipient_locations", "Recipient Location"),
    "performance_pr": ("place_of_performance_locations", "Primary Place of Performance"),
}
FIELDS = [
    "Award ID",
    "Recipient Name",
    "Award Amount",
    "Recipient Location",
    "Primary Place of Performance",
    "CFDA Number",
]
LIMIT = 100
MAX_RECORDS = 9900
MAX_RESPONSE_BYTES = 10 * 1024 * 1024


def digest(buf: bytes) -> str:
    return hashlib.sha256(buf).hexdigest()


def filters_for(scope: str) -> dict:
    if scope not in SCOPES:
        raise ValueError("UNKNOWN_LOCATION_SCOPE")
    return {
        "award_type_codes": list(CODES),
        SCOPES[scope][0]: [{"country": "USA", "state": "PR"}],
        "time_period": [PERIOD],
    }


def post_json(url: str, body: dict, path: Path) -> dict:
    raw_body = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.with_suffix(".request.json").write_bytes(raw_body)
    req = Request(
        url,
        data=raw_body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "PR-Registry-Enumerate-Bounded-Awards/1.0",
        },
        method="POST",
    )
    with urlopen(req, timeout=60) as rsp:
        if rsp.geturl() != url:
            raise ValueError("SOURCE_ENDPOINT_DRIFT")
        raw = rsp.read(MAX_RESPONSE_BYTES + 1)
    if not raw or len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("SOURCE_RESPONSE_SIZE_REJECTED")
    path.write_bytes(raw)
    return json.loads(raw)


def count_value(obj: dict) -> int:
    v = obj.get("results", {}).get("grants")
    if obj.get("spending_level") != "awards" or type(v) is not int or v < 0:
        raise ValueError("INADMISSIBLE_COUNT_RESPONSE")
    return v


def validate_page(obj: dict, page: int, scope: str) -> tuple[list[dict], bool]:
    if not isinstance(obj, dict) or not isinstance(obj.get("results"), list):
        raise ValueError("MALFORMED_AWARD_RESPONSE")
    meta = obj.get("page_metadata")
    if not isinstance(meta, dict) or meta.get("page") != page:
        raise ValueError("PAGE_NUMBER_DRIFT")
    if type(meta.get("hasNext")) is not bool:
        raise ValueError("PAGINATION_STATE_MISSING")
    rows = obj["results"]
    if len(rows) > LIMIT:
        raise ValueError("OVERFULL_PAGE")
    geographic_field = SCOPES[scope][1]
    page_ids = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("MALFORMED_AWARD_RECORD")
        val = row.get("generated_internal_id")
        if val is None or not str(val).strip():
            raise ValueError("AWARD_INTERNAL_ID_MISSING")
        val = str(val)
        if val in page_ids:
            raise ValueError("DUPLICATE_ID_WITHIN_PAGE")
        page_ids.add(val)
        geo = row.get(geographic_field)
        if not isinstance(geo, dict) or geo.get("state_code") != "PR":
            raise ValueError("FILTERED_GEO_NOT_PR")
    return rows, meta["hasNext"]


def enumerate_scope(scope: str, outdir: Path) -> tuple[dict, dict[str, dict]]:
    folder = outdir / scope
    folder.mkdir(parents=True, exist_ok=True)
    filters = filters_for(scope)
    count_body = {"filters": filters, "spending_level": "awards", "subawards": False}
    start = count_value(post_json(COUNT_URL, count_body, folder / "count_before_raw.json"))
    if start <= 0:
        raise ValueError("EMPTY_COUNT_REQUIRES_SPECIAL_ADJUDICATION")
    if start > MAX_RECORDS:
        raise ValueError("COUNT_EXCEEDS_9900_SAFETY_CEILING_PARTITION_REQUIRED")
    expected_pages = math.ceil(start / LIMIT)
    seen = {}
    page_receipts = []
    for page in range(1, expected_pages + 1):
        body = {
            "filters": filters,
            "fields": FIELDS,
            "limit": LIMIT,
            "order": "desc",
            "page": page,
            "sort": "Award Amount",
            "spending_level": "awards",
            "subawards": False,
        }
        filename = folder / f"page_{page:04}_raw.json"
        obj = post_json(URL, body, filename)
        rows, has_next = validate_page(obj, page, scope)
        if not rows:
            raise ValueError("EMPTY_PAGE_BEFORE_COUNT_EXHAUSTION")
        for row in rows:
            identity = str(row["generated_internal_id"])
            if identity in seen:
                raise ValueError("REPEATED_INTERNAL_ID_ACROSS_PAGES")
            seen[identity] = row
        page_receipts.append(
            {
                "page": page,
                "rows": len(rows),
                "raw_sha256": digest(filename.read_bytes()),
                "hasNext": has_next,
            }
        )
        if len(seen) < start and not has_next:
            raise ValueError("FALSE_TERMINAL_PAGE_BEFORE_COUNT")
        if len(seen) > start:
            raise ValueError("MORE_ROWS_THAN_COUNT")
    if len(seen) != start:
        raise ValueError("AWARD_ID_SET_NOT_CONSERVED")
    # Mandatory independent sentinel even when hasNext=false. An issue reports
    # false hasNext at 10,000 records with later pages still containing awards.
    sentinel_page = expected_pages + 1
    sentinel_path = folder / f"page_{sentinel_page:04}_sentinel_raw.json"
    sentinel = post_json(
        URL,
        {
            "filters": filters,
            "fields": FIELDS,
            "limit": LIMIT,
            "order": "desc",
            "page": sentinel_page,
            "sort": "Award Amount",
            "spending_level": "awards",
            "subawards": False,
        },
        sentinel_path,
    )
    extra, _ = validate_page(sentinel, sentinel_page, scope)
    if extra:
        raise ValueError("SENTINEL_HAS_ADDITIONAL_AWARDS")
    final = count_value(post_json(COUNT_URL, count_body, folder / "count_after_raw.json"))
    if final != start:
        raise ValueError("SOURCE_COUNT_CHANGED_DURING_ENUMERATION")
    id_list = sorted(seen)
    (folder / "award_internal_ids.json").write_text(json.dumps(id_list, indent=2) + "\n")
    bound_numbers = {}
    for award_id, record in seen.items():
        cfda = record.get("CFDA Number")
        if cfda:
            bound_numbers[award_id] = str(cfda)
    (folder / "candidate_assistance_listing_numbers.json").write_text(
        json.dumps(bound_numbers, indent=2, sort_keys=True) + "\n"
    )
    return {
        "count_before": start,
        "count_after": final,
        "raw_pages": expected_pages + 1,
        "award_ids": len(seen),
        "geographic_scope": scope,
        "page_receipts": page_receipts,
        "listing_number_candidates": len(bound_numbers),
        "bound_canonical_pr_programs": 0,
        "membership_sha256": digest(("\n".join(id_list) + "\n").encode()),
        "status": "BOUNDED_ID_MEMBERSHIP_COUNT_CONSERVED",
    }, seen


def run(outdir: Path) -> int:
    outdir.mkdir(parents=True, exist_ok=True)
    receipt: dict[str, Any] = {
        "schema": "pr_program_fy2026_grant_awards_paged_v1",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "state": "BLOCKED",
        "universe": "FY2026_PR_GRANTS_02_03_04_05_PRIME_AWARDS",
        "complete_all_federal_programs": False,
        "complete_all_fiscal_years": False,
        "complete_all_award_types": False,
        "complete_subawards": False,
        "canonical_programs_certified": False,
        "registry_certified": False,
        "scopes": {},
    }
    sets = {}
    for name in SCOPES:
        try:
            state, rows = enumerate_scope(name, outdir)
            receipt["scopes"][name] = state
            sets[name] = set(rows)
        except Exception as err:
            receipt["scopes"][name] = {
                "status": "BLOCKED",
                "error_type": type(err).__name__,
                "error_message": str(err)[:500],
            }
    if len(sets) == len(SCOPES):
        left, right = sets["recipient_pr"], sets["performance_pr"]
        membership = {
            "intersection_count": len(left & right),
            "recipient_only_count": len(left - right),
            "performance_only_count": len(right - left),
            "union_count": len(left | right),
            "symmetric_difference_count": len(left ^ right),
            "intersection_ids_sha256": digest(("\n".join(sorted(left & right)) + "\n").encode()),
            "never_sum_geo_counts_as_unique_programs": True,
        }
        (outdir / "cross_geography_set_algebra.json").write_text(
            json.dumps(membership, indent=2, sort_keys=True) + "\n"
        )
        receipt["cross_geography"] = membership
        receipt["state"] = "BOUNDED_FY2026_GRANT_MEMBERSHIP_ACQUIRED"
    (outdir / "page_ledger_receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    )
    print(
        json.dumps(
            {
                "state": receipt["state"],
                "scopes": {
                    k: {x: v[x] for x in ("status", "award_ids", "count_before") if x in v}
                    for k, v in receipt["scopes"].items()
                },
                "cross_geography": receipt.get("cross_geography"),
            },
            sort_keys=True,
        )
    )
    return 0 if receipt["state"] == "BOUNDED_FY2026_GRANT_MEMBERSHIP_ACQUIRED" else 2


if __name__ == "__main__":
    raise SystemExit(
        run(
            Path(sys.argv[1])
            if len(sys.argv) > 1
            else Path("outputs/pr_registry_fy2026_grant_membership")
        )
    )
