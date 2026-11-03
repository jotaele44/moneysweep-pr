#!/usr/bin/env python3
"""Bounded FY2023/FY2024 PR other-assistance primary-award census, fail closed."""

from __future__ import annotations
import hashlib
import json
import math
import sys
from pathlib import Path
from datetime import datetime, timezone
from urllib.request import Request, urlopen

COUNT = "https://api.usaspending.gov/api/v2/search/spending_by_award_count/"
AWARDS = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
CODES = ["09", "11", "F005", "F008", "F009", "F010"]
GEO = {"recipient_pr": "recipient_locations", "performance_pr": "place_of_performance_locations"}
FIELDS = [
    "Award ID",
    "Recipient Name",
    "Award Amount",
    "Recipient Location",
    "Primary Place of Performance",
    "CFDA Number",
]
LIMIT = 100
MAX_AWARDS = 9900
MAX_BYTES = 5_000_000


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def filters(geo: str, year: int) -> dict:
    if year not in (2023, 2024):
        raise ValueError("UNAUTHORIZED_YEAR")
    if geo not in GEO:
        raise ValueError("UNKNOWN_GEOGRAPHY")
    return {
        "award_type_codes": CODES,
        GEO[geo]: [{"country": "USA", "state": "PR"}],
        "time_period": [{"start_date": f"{year - 1}-10-01", "end_date": f"{year}-09-30"}],
    }


def request(url: str, body: dict, path: Path) -> dict:
    data = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    path.with_suffix(".request.json").write_bytes(data)
    req = Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "PR-registry-audit-read-only/1.0",
        },
    )
    with urlopen(req, timeout=75) as res:
        if res.geturl() != url:
            raise ValueError("SOURCE_ENDPOINT_DRIFT")
        raw = res.read(MAX_BYTES + 1)
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("INVALID_SOURCE_RESPONSE_SIZE")
    path.write_bytes(raw)
    return json.loads(raw)


def count(response: dict) -> int:
    if response.get("spending_level") != "awards":
        raise ValueError("WRONG_SPENDING_LEVEL")
    values = response.get("results")
    if not isinstance(values, dict):
        raise ValueError("BAD_COUNT_RESPONSE")
    n = values.get("other")
    if type(n) is not int or n < 0:
        raise ValueError("BAD_OTHER_COUNT")
    return n


def page(response: dict, geo: str, pageno: int) -> tuple[list[dict], bool]:
    rows = response.get("results")
    meta = response.get("page_metadata")
    if not isinstance(rows, list) or not isinstance(meta, dict):
        raise ValueError("MALFORMED_PAGE")
    if meta.get("page") != pageno or type(meta.get("hasNext")) is not bool:
        raise ValueError("PAGINATION_DRIFT")
    if len(rows) > LIMIT:
        raise ValueError("OVERFULL_PAGE")
    ids = set()
    place = "Recipient Location" if geo == "recipient_pr" else "Primary Place of Performance"
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("MALFORMED_RECORD")
        ident = row.get("generated_internal_id")
        if ident is None or not str(ident).strip():
            raise ValueError("MISSING_AWARD_STABLE_ID")
        if str(ident) in ids:
            raise ValueError("DUPLICATE_ID_WITHIN_PAGE")
        ids.add(str(ident))
        loc = row.get(place)
        if not isinstance(loc, dict) or loc.get("state_code") != "PR":
            raise ValueError("FILTERED_GEOGRAPHY_NOT_PR")
    return rows, meta["hasNext"]


def acquire_geo(target: Path, geo: str, year: int) -> tuple[dict, set[str]]:
    target.mkdir(parents=True, exist_ok=True)
    f = filters(geo, year)
    body = {"filters": f, "spending_level": "awards", "subawards": False}
    n = count(request(COUNT, body, target / "count_before.json"))
    if n < 1 or n > MAX_AWARDS:
        raise ValueError("COUNT_OUTSIDE_BOUNDED_PARTITION_1_TO_9900")
    expected = math.ceil(n / LIMIT)
    ids = set()
    ledger = []
    for i in range(1, expected + 1):
        payload = {
            "filters": f,
            "fields": FIELDS,
            "page": i,
            "limit": LIMIT,
            "sort": "Award Amount",
            "order": "desc",
            "spending_level": "awards",
            "subawards": False,
        }
        path = target / f"page_{i:04d}.json"
        rows, next_page = page(request(AWARDS, payload, path), geo, i)
        if not rows:
            raise ValueError("EARLY_EMPTY_PAGE")
        for row in rows:
            key = str(row["generated_internal_id"])
            if key in ids:
                raise ValueError("DUPLICATE_ID_ACROSS_PAGES")
            ids.add(key)
        if len(ids) < n and not next_page:
            raise ValueError("PREMATURE_TERMINAL_PAGE")
        if len(ids) > n:
            raise ValueError("COUNT_EXCEEDED")
        ledger.append({"page": i, "rows": len(rows), "raw_sha256": sha(path.read_bytes())})
    if len(ids) != n:
        raise ValueError("ID_COUNT_CONSERVATION_FAIL")
    terminal = expected + 1
    path = target / f"page_{terminal:04d}_sentinel.json"
    payload = {
        "filters": f,
        "fields": FIELDS,
        "page": terminal,
        "limit": LIMIT,
        "sort": "Award Amount",
        "order": "desc",
        "spending_level": "awards",
        "subawards": False,
    }
    beyond, _ = page(request(AWARDS, payload, path), geo, terminal)
    if beyond:
        raise ValueError("NONEMPTY_TERMINAL_SENTINEL")
    after = count(request(COUNT, body, target / "count_after.json"))
    if after != n:
        raise ValueError("MUTABLE_SOURCE_COUNT_CHANGED")
    ordered = sorted(ids)
    (target / "award_ids.json").write_text(json.dumps(ordered, indent=2) + "\n")
    return {
        "state": "ID_SET_CONSERVED_IN_SCOPE",
        "count_before": n,
        "count_after": after,
        "ids": len(ids),
        "pages": len(ledger),
        "sentinel_page": terminal,
        "sentinel_empty": True,
        "ids_sha256": sha(("\n".join(ordered) + "\n").encode()),
        "page_ledger": ledger,
    }, ids


def receipt_schema(year: int) -> str:
    if year not in (2023, 2024):
        raise ValueError("UNAUTHORIZED_YEAR")
    return f"pr_registry_fy{year}_expanded_other_award_ids_v1"


def run(target: Path, year: int) -> int:
    if year not in (2023, 2024):
        raise ValueError("UNAUTHORIZED_YEAR")
    target.mkdir(parents=True, exist_ok=True)
    result = {
        "schema": receipt_schema(year),
        "retrieved_utc": datetime.now(timezone.utc).isoformat(),
        "code_set": CODES,
        "scope": f"FY{year}_other_financial_assistance_PR_two_geographies",
        "geographies": {},
        "certificate": "WITHHELD",
        "all_years_complete": False,
        "canonical_program_identities": False,
        "subawards_complete": False,
        "source_snapshot_complete": False,
        "state": "BLOCKED",
    }
    sets = {}
    for name in GEO:
        try:
            evidence, ids = acquire_geo(target / name, name, year)
            result["geographies"][name] = evidence
            sets[name] = ids
        except Exception as ex:
            result["geographies"][name] = {
                "state": "BLOCKED",
                "error_type": type(ex).__name__,
                "message": str(ex)[:500],
            }
    if len(sets) == 2:
        a, b = sets.values()
        result["set_algebra"] = {
            "intersection": len(a & b),
            "recipient_only": len(a - b),
            "performance_only": len(b - a),
            "union": len(a | b),
            "symmetric_difference": len(a ^ b),
        }
        result["state"] = "BOUNDED_TWO_GEO_MEMBERSHIP_PASS"
    (target / "receipt.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "state": result["state"],
                "geographies": {
                    k: {x: y[x] for x in ("state", "ids", "count_before", "message") if x in y}
                    for k, y in result["geographies"].items()
                },
                "set_algebra": result.get("set_algebra"),
            },
            sort_keys=True,
        )
    )
    return 0 if result["state"] == "BOUNDED_TWO_GEO_MEMBERSHIP_PASS" else 2


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: enumerate_other_fy2023_fy2024.py FISCAL_YEAR OUTPUT_DIR")
    raise SystemExit(run(Path(sys.argv[2]), int(sys.argv[1])))
