#!/usr/bin/env python3
"""Versioned USAspending assistance-type code comparison, not an identity census.

Maintains the 02-11 legacy code universe and newly defined F001-F010 code
universe as separately named source scopes. Source totals are observations,
never canonical awards/program IDs or proof of completeness. Fail closed.
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

API = "https://api.usaspending.gov/api/v2/search/spending_by_award_count/"
YEARS = tuple(range(2022, 2027))
GEOGRAPHIES = {
    "recipient_pr": "recipient_locations",
    "performance_pr": "place_of_performance_locations",
}
LEGACY = ("02", "03", "04", "05", "06", "07", "08", "09", "10", "11")
NEW = tuple(f"F{i:03d}" for i in range(1, 11))
MODES = {"legacy_only": LEGACY, "expanded": LEGACY + NEW}
GROUPS = ("grants", "loans", "direct_payments", "other")
MAX_BYTES = 1_048_576


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encode_body(fy: int, geo: str, mode: str) -> bytes:
    if fy not in YEARS or geo not in GEOGRAPHIES or mode not in MODES:
        raise ValueError("INVALID_SCOPED_QUERY")
    filters: dict[str, Any] = {
        "award_type_codes": list(MODES[mode]),
        GEOGRAPHIES[geo]: [{"country": "USA", "state": "PR"}],
        "time_period": [{"start_date": f"{fy - 1}-10-01", "end_date": f"{fy}-09-30"}],
    }
    payload = {"filters": filters, "spending_level": "awards", "subawards": False}
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def validate_count(raw: bytes) -> dict[str, int]:
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get("spending_level") != "awards":
        raise ValueError("INVALID_COUNT_SPENDING_LEVEL")
    result = value.get("results")
    if not isinstance(result, dict):
        raise ValueError("COUNT_RESULTS_MISSING")
    selected: dict[str, int] = {}
    for kind in GROUPS:
        count = result.get(kind)
        if type(count) is not int or count < 0:
            raise ValueError("INVALID_COUNT_" + kind)
        selected[kind] = count
    for kind in ("contracts", "idvs"):
        count = result.get(kind)
        if type(count) is not int or count != 0:
            raise ValueError("PROCUREMENT_CROSSCONTAMINATION_" + kind)
    return selected


def fetch(body: bytes) -> bytes:
    request = Request(
        API,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "PR-Program-Registry-Taxonomy-Comparison/1.0",
        },
    )
    with urlopen(request, timeout=75) as response:
        if response.geturl() != API:
            raise RuntimeError("ENDPOINT_DRIFT")
        raw = response.read(MAX_BYTES + 1)
    if not raw or len(raw) > MAX_BYTES:
        raise RuntimeError("RESPONSE_SIZE_REJECTED")
    return raw


def compare(legacy: dict[str, int], expanded: dict[str, int]) -> dict:
    diffs = {key: expanded[key] - legacy[key] for key in GROUPS}
    if any(delta < 0 for delta in diffs.values()):
        raise ValueError("EXPANDED_SCOPE_SMALLER_THAN_LEGACY")
    return {
        "legacy": legacy,
        "expanded": expanded,
        "expanded_minus_legacy": diffs,
        "expansion_nonzero": any(diffs.values()),
        "candidate_identity_promotions": 0,
    }


def run(outdir: Path) -> int:
    outdir.mkdir(parents=True, exist_ok=True)
    receipt: dict[str, Any] = {
        "schema": "pr_registry_source_taxonomy_v13",
        "retrieved_utc": datetime.now(timezone.utc).isoformat(),
        "authority": "USAspending_public_award_count_API",
        "source_endpoint": API,
        "scope": "FY2022_FY2026_PR_RECIPIENT_AND_PERFORMANCE",
        "legacy_codes": list(LEGACY),
        "new_codes": list(NEW),
        "modes": list(MODES),
        "sources": {},
        "comparisons": {},
        "status": "BLOCKED",
        "source_member_enumeration": False,
        "full_award_census": False,
        "federal_program_identities": False,
        "complete_historical_PR_registry": False,
        "certification": "WITHHELD",
    }
    for fy in YEARS:
        for geo in GEOGRAPHIES:
            samples = {}
            for mode in MODES:
                name = f"fy{fy}_{geo}_{mode}"
                payload = encode_body(fy, geo, mode)
                (outdir / (name + "_request.json")).write_bytes(payload)
                try:
                    raw = fetch(payload)
                    (outdir / (name + "_raw.json")).write_bytes(raw)
                    values = validate_count(raw)
                    receipt["sources"][name] = {
                        "status": "COUNT_BYTES_VERIFIED",
                        "request_sha256": sha(payload),
                        "response_sha256": sha(raw),
                        "response_size": len(raw),
                        "counts": values,
                        "program_or_award_membership": False,
                    }
                    samples[mode] = values
                except Exception as err:
                    detail = str(err)
                    if isinstance(err, HTTPError):
                        detail = err.read(8192).decode("utf-8", "replace")
                    receipt["sources"][name] = {
                        "status": "FAILED_SOURCE",
                        "error_type": type(err).__name__,
                        "error_detail": detail[:1800],
                    }
            if len(samples) == 2:
                key = f"fy{fy}_{geo}"
                try:
                    receipt["comparisons"][key] = compare(
                        samples["legacy_only"], samples["expanded"]
                    )
                except Exception as err:
                    receipt["comparisons"][key] = {"status": "UNRESOLVED", "error": str(err)}
    passes = len(receipt["sources"]) == len(YEARS) * len(GEOGRAPHIES) * len(MODES)
    passes &= all(x["status"] == "COUNT_BYTES_VERIFIED" for x in receipt["sources"].values())
    passes &= len(receipt["comparisons"]) == len(YEARS) * len(GEOGRAPHIES)
    passes &= all("expanded_minus_legacy" in x for x in receipt["comparisons"].values())
    if passes:
        receipt["status"] = "BOUNDED_LEGACY_VS_EXPANDED_COUNT_COMPARISON_PASS"
    (outdir / "taxonomy_receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "comparisons": receipt["comparisons"],
                "failures": {
                    k: v
                    for k, v in receipt["sources"].items()
                    if v["status"] != "COUNT_BYTES_VERIFIED"
                },
            },
            sort_keys=True,
        )
    )
    return 0 if passes else 2


if __name__ == "__main__":
    raise SystemExit(
        run(
            Path(sys.argv[1])
            if len(sys.argv) > 1
            else Path("outputs/pr_registry_taxonomy_comparison")
        )
    )
