"""Dry-run-first LDA.gov API adapter.

This adapter normalizes the public LDA.gov API into reproducible CSV outputs.
Default execution uses deterministic synthetic fixtures and performs no network
calls. Live HTTP access is only used when ``--live`` is explicitly supplied.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

LDA_BASE_URL = "https://lda.gov/api/v1/"
SOURCE_ID = "lda_gov"
SOURCE_FAMILY = "federal_lobbying"
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_RETRIES = 3

EXPECTED_ENDPOINTS: dict[str, str] = {
    "filings": "filings/",
    "contributions": "contributions/",
    "registrants": "registrants/",
    "clients": "clients/",
    "lobbyists": "lobbyists/",
    "constants/filing/filingtypes": "constants/filing/filingtypes/",
    "constants/filing/lobbyingactivityissues": "constants/filing/lobbyingactivityissues/",
    "constants/filing/governmententities": "constants/filing/governmententities/",
    "constants/general/countries": "constants/general/countries/",
    "constants/general/states": "constants/general/states/",
    "constants/lobbyist/prefixes": "constants/lobbyist/prefixes/",
    "constants/lobbyist/suffixes": "constants/lobbyist/suffixes/",
    "constants/contribution/itemtypes": "constants/contribution/itemtypes/",
}

OUTPUTS: dict[str, tuple[str, str]] = {
    "registrants": ("outputs/normalized/lda/lda_registrants.csv", "T1"),
    "clients": ("outputs/normalized/lda/lda_clients.csv", "T1"),
    "lobbyists": ("outputs/normalized/lda/lda_lobbyists.csv", "T1"),
    "filings": ("outputs/normalized/lda/lda_filings.csv", "T1"),
    "contributions": ("outputs/normalized/lda/lda_contributions.csv", "T1"),
    "constants/filing/filingtypes": ("outputs/reference/lda/lda_ref_filing_types.csv", "T1"),
    "constants/filing/lobbyingactivityissues": ("outputs/reference/lda/lda_ref_lobbying_issues.csv", "T1"),
    "constants/filing/governmententities": ("outputs/reference/lda/lda_ref_government_entities.csv", "T1"),
    "constants/general/countries": ("outputs/reference/lda/lda_ref_countries.csv", "T1"),
    "constants/general/states": ("outputs/reference/lda/lda_ref_states.csv", "T1"),
    "constants/lobbyist/prefixes": ("outputs/reference/lda/lda_ref_lobbyist_prefixes.csv", "T1"),
    "constants/lobbyist/suffixes": ("outputs/reference/lda/lda_ref_lobbyist_suffixes.csv", "T1"),
    "constants/contribution/itemtypes": ("outputs/reference/lda/lda_ref_contribution_item_types.csv", "T1"),
}

SYNTHETIC_ROOT = {
    key: f"{LDA_BASE_URL}{path}?format=api" for key, path in EXPECTED_ENDPOINTS.items()
}

SYNTHETIC_FIXTURES: dict[str, Any] = {
    "registrants": {
        "count": 1,
        "next": None,
        "previous": None,
        "results": [
            {
                "id": "REG-001",
                "name": "MZLS LLC",
                "ppb_country": "US",
                "ppb_state": "PR",
                "address_1": "100 Demo Street",
                "city": "San Juan",
                "zip": "00901",
            }
        ],
    },
    "clients": {
        "count": 1,
        "next": None,
        "previous": None,
        "results": [
            {
                "id": "CLI-001",
                "name": "SENATE OF PUERTO RICO",
                "country": "US",
                "state": "PR",
                "address_1": "Capitol Building",
                "city": "San Juan",
                "zip": "00901",
            }
        ],
    },
    "lobbyists": [
        {
            "id": "LOB-001",
            "first_name": "Ana",
            "middle_name": "M.",
            "last_name": "Rivera",
            "suffix": "",
            "prefix": "Ms.",
        }
    ],
    "filings": {
        "count": 1,
        "next": None,
        "previous": None,
        "results": [
            {
                "id": "FIL-001",
                "uuid": "00000000-0000-0000-0000-000000000001",
                "filing_url": "https://lda.gov/filing/demo",
                "filing_type": "1st Quarter - Report",
                "filing_year": "2026",
                "filing_period": "Q1",
                "posted_date": "2026-04-20",
                "registrant": {"id": "REG-001", "name": "MZLS LLC"},
                "client": {"id": "CLI-001", "name": "SENATE OF PUERTO RICO"},
                "amount_reported": "30000.00",
                "lobbying_issues": ["BUD"],
                "government_entities": ["SENATE"],
            }
        ],
    },
    "contributions": {
        "count": 1,
        "next": None,
        "previous": None,
        "results": [
            {
                "id": "CON-001",
                "filing_id": "FIL-001",
                "registrant": {"id": "REG-001", "name": "MZLS LLC"},
                "client": {"id": "CLI-001", "name": "SENATE OF PUERTO RICO"},
                "item_type": "Contribution",
                "amount": "1000.00",
                "contribution_date": "2026-03-15",
                "payee_or_recipient": "Demo Committee",
            }
        ],
    },
    "constants/filing/filingtypes": [{"id": "Q1", "code": "Q1", "name": "1st Quarter - Report"}],
    "constants/filing/lobbyingactivityissues": [{"id": "BUD", "code": "BUD", "name": "Budget/Appropriations"}],
    "constants/filing/governmententities": [{"id": "SENATE", "code": "SENATE", "name": "U.S. Senate"}],
    "constants/general/countries": [{"id": "US", "code": "US", "name": "United States"}],
    "constants/general/states": [{"id": "PR", "code": "PR", "name": "Puerto Rico"}],
    "constants/lobbyist/prefixes": [{"id": "MS", "code": "Ms.", "name": "Ms."}],
    "constants/lobbyist/suffixes": [{"id": "JR", "code": "Jr.", "name": "Jr."}],
    "constants/contribution/itemtypes": [{"id": "CONTRIB", "code": "CONTRIB", "name": "Contribution"}],
}

Fetcher = Callable[[str], Any]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def endpoint_url(path: str, fmt: str = "json") -> str:
    suffix = path if path.endswith("/") else f"{path}/"
    return f"{urljoin(LDA_BASE_URL, suffix)}?format={fmt}"


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def coalesce(record: dict[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        value = record.get(key)
        if value is not None and value != "":
            return str(value)
    return default


def nested_id(value: Any) -> str:
    if isinstance(value, dict):
        return coalesce(value, "id", "registrant_id", "client_id", "uuid")
    if value is None:
        return ""
    return str(value)


def nested_name(value: Any) -> str:
    if isinstance(value, dict):
        return coalesce(value, "name", "registrant_name", "client_name")
    if value is None:
        return ""
    return str(value)


def pipe_join(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "|".join(str(item.get("code") if isinstance(item, dict) else item) for item in value)
    return str(value)


def http_json_fetcher(url: str, *, timeout: int = DEFAULT_TIMEOUT_SECONDS, retries: int = DEFAULT_RETRIES) -> Any:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            req = Request(url, headers={"Accept": "application/json", "User-Agent": "Contract-Sweeper-LDA/1.0"})
            with urlopen(req, timeout=timeout) as resp:  # noqa: S310 - public read-only API endpoint
                return json.loads(resp.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < retries - 1:
                time.sleep(0.5 * (2 ** attempt))
    raise RuntimeError(f"LDA fetch failed after {retries} attempts for {url}: {last_error}")


def discover_endpoints(*, live: bool = False, fetcher: Fetcher | None = None) -> tuple[dict[str, str], list[str]]:
    if not live:
        return dict(SYNTHETIC_ROOT), []
    data = (fetcher or http_json_fetcher)(endpoint_url("", fmt="json"))
    endpoints = {key: str(data[key]) for key in EXPECTED_ENDPOINTS if isinstance(data, dict) and key in data}
    missing = sorted(set(EXPECTED_ENDPOINTS) - set(endpoints))
    for key in missing:
        endpoints[key] = endpoint_url(EXPECTED_ENDPOINTS[key])
    return endpoints, missing


def _records_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        return [r for r in payload["results"] if isinstance(r, dict)]
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        return [payload]
    return []


def collect_records(endpoint_key: str, url: str, *, live: bool, limit: int | None, fetcher: Fetcher | None = None) -> list[dict[str, Any]]:
    if not live:
        return _records_from_payload(SYNTHETIC_FIXTURES[endpoint_key])[:limit]

    out: list[dict[str, Any]] = []
    next_url: str | None = url
    call_fetcher = fetcher or http_json_fetcher
    while next_url:
        payload = call_fetcher(next_url)
        out.extend(_records_from_payload(payload))
        if limit is not None and len(out) >= limit:
            return out[:limit]
        next_url = payload.get("next") if isinstance(payload, dict) else None
    return out


def metadata(record: dict[str, Any], endpoint_key: str, url: str, retrieved_at: str, *, evidence_tier: str, include_raw: bool) -> dict[str, Any]:
    api_id = coalesce(record, "id", "uuid", "filing_uuid", "filing_id", "registrant_id", "client_id", default=stable_hash(record)[:16])
    meta = {
        "source_id": SOURCE_ID,
        "source_family": SOURCE_FAMILY,
        "source_endpoint": endpoint_key,
        "source_url": url,
        "retrieved_at": retrieved_at,
        "api_record_id": api_id,
        "record_hash": stable_hash(record),
        "raw_payload_stored": bool(include_raw),
        "evidence_tier": evidence_tier,
    }
    if include_raw:
        meta["raw_payload_json"] = json.dumps(record, sort_keys=True, ensure_ascii=False)
    return meta


def normalize_record(endpoint_key: str, record: dict[str, Any], url: str, retrieved_at: str, *, evidence_tier: str, include_raw: bool = False) -> dict[str, Any]:
    meta = metadata(record, endpoint_key, url, retrieved_at, evidence_tier=evidence_tier, include_raw=include_raw)

    if endpoint_key == "registrants":
        row = {
            "registrant_id": coalesce(record, "registrant_id", "id"),
            "registrant_name": coalesce(record, "registrant_name", "name"),
            "registrant_ppb_country": coalesce(record, "registrant_ppb_country", "ppb_country", "country"),
            "registrant_ppb_state": coalesce(record, "registrant_ppb_state", "ppb_state", "state"),
            "registrant_address": " ".join(filter(None, [coalesce(record, "address_1", "address"), coalesce(record, "address_2")])).strip(),
            "registrant_city": coalesce(record, "city", "registrant_city"),
            "registrant_zip": coalesce(record, "zip", "zip_code", "registrant_zip"),
        }
    elif endpoint_key == "clients":
        row = {
            "client_id": coalesce(record, "client_id", "id"),
            "client_name": coalesce(record, "client_name", "name"),
            "client_country": coalesce(record, "client_country", "country"),
            "client_state": coalesce(record, "client_state", "state"),
            "client_address": " ".join(filter(None, [coalesce(record, "address_1", "address"), coalesce(record, "address_2")])).strip(),
            "client_city": coalesce(record, "city", "client_city"),
            "client_zip": coalesce(record, "zip", "zip_code", "client_zip"),
        }
    elif endpoint_key == "lobbyists":
        row = {
            "lobbyist_id": coalesce(record, "lobbyist_id", "id"),
            "first_name": coalesce(record, "first_name"),
            "middle_name": coalesce(record, "middle_name"),
            "last_name": coalesce(record, "last_name"),
            "suffix": coalesce(record, "suffix"),
            "prefix": coalesce(record, "prefix"),
        }
    elif endpoint_key == "filings":
        registrant = record.get("registrant") or {}
        client = record.get("client") or {}
        row = {
            "filing_id": coalesce(record, "filing_id", "id"),
            "filing_uuid_or_url": coalesce(record, "filing_uuid", "uuid", "filing_url", "url"),
            "filing_type": coalesce(record, "filing_type", "filing_type_display"),
            "filing_year": coalesce(record, "filing_year", "year"),
            "filing_period": coalesce(record, "filing_period", "period"),
            "posted_date": coalesce(record, "posted_date", "filing_date"),
            "registrant_id": coalesce(record, "registrant_id", default=nested_id(registrant)),
            "registrant_name": coalesce(record, "registrant_name", default=nested_name(registrant)),
            "client_id": coalesce(record, "client_id", default=nested_id(client)),
            "client_name": coalesce(record, "client_name", default=nested_name(client)),
            "amount_reported": coalesce(record, "amount_reported", "income", "expenses"),
            "lobbying_issues": pipe_join(record.get("lobbying_issues") or record.get("general_issue_codes")),
            "government_entities": pipe_join(record.get("government_entities")),
        }
    elif endpoint_key == "contributions":
        registrant = record.get("registrant") or {}
        client = record.get("client") or {}
        row = {
            "contribution_id": coalesce(record, "contribution_id", "id"),
            "filing_id": coalesce(record, "filing_id"),
            "registrant_id": coalesce(record, "registrant_id", default=nested_id(registrant)),
            "registrant_name": coalesce(record, "registrant_name", default=nested_name(registrant)),
            "client_id": coalesce(record, "client_id", default=nested_id(client)),
            "client_name": coalesce(record, "client_name", default=nested_name(client)),
            "item_type": coalesce(record, "item_type", "type"),
            "amount": coalesce(record, "amount", "contribution_amount"),
            "contribution_date": coalesce(record, "contribution_date", "date"),
            "payee_or_recipient": coalesce(record, "payee_or_recipient", "recipient", "payee"),
        }
    else:
        row = {
            "reference_id": coalesce(record, "id", "code", "value", default=stable_hash(record)[:16]),
            "code": coalesce(record, "code", "value", "name"),
            "name": coalesce(record, "name", "label", "description"),
            "description": coalesce(record, "description"),
        }
    return {**row, **meta}


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_checkpoint(root: Path, payload: dict[str, Any]) -> None:
    checkpoint = root / "reports" / "lda_api_checkpoint.json"
    write_json(checkpoint, payload)


def build_static_seed_report(root: Path, endpoints: dict[str, str], normalized_outputs: list[str], reference_outputs: list[str], created_at: str) -> dict[str, Any]:
    replacement_decision = {
        "uploaded_static_lda_registrant_client_filing_snapshots": "replaced_by_api",
        "Registrants.pdf": "retained_as_fixture",
        "manual_lda_extracts": "retained_as_archival_snapshot",
    }
    return {
        "source_id": SOURCE_ID,
        "authority_level": "api_authoritative",
        "static_seed_role_after_adapter": "regression_fixture",
        "endpoints_discovered": sorted(endpoints),
        "normalized_outputs": normalized_outputs,
        "reference_outputs": reference_outputs,
        "replacement_decision": replacement_decision,
        "unresolved_static_seed_files": [],
        "created_at": created_at,
    }


def run(*, output_dir: Path, live: bool = False, limit: int | None = None, include_raw: bool = False, fetcher: Fetcher | None = None) -> dict[str, Any]:
    retrieved_at = utc_now_iso()
    blockers: list[str] = []
    root_discovery_ok: bool | str | None = "skipped_dry_run"

    try:
        endpoints, missing = discover_endpoints(live=live, fetcher=fetcher)
        if live:
            root_discovery_ok = not missing
        if missing:
            blockers.append("missing_or_changed_endpoints:" + ",".join(missing))
    except Exception as exc:  # noqa: BLE001 - structured readiness report instead of crash for discovery
        endpoints = {key: endpoint_url(path) for key, path in EXPECTED_ENDPOINTS.items()}
        root_discovery_ok = False
        blockers.append(f"root_discovery_failed:{exc}")

    outputs_created: list[str] = []
    normalized_outputs: list[str] = []
    reference_outputs: list[str] = []
    normalization_ok = True

    for endpoint_key, (relative_path, evidence_tier) in OUTPUTS.items():
        url = endpoints.get(endpoint_key) or endpoint_url(EXPECTED_ENDPOINTS[endpoint_key])
        try:
            records = collect_records(endpoint_key, url, live=live, limit=limit, fetcher=fetcher)
            rows = [normalize_record(endpoint_key, r, url, retrieved_at, evidence_tier=evidence_tier, include_raw=include_raw) for r in records]
        except Exception as exc:  # noqa: BLE001 - endpoint-level warning, keep unrelated endpoints alive
            normalization_ok = False
            blockers.append(f"{endpoint_key}:{exc}")
            rows = []
        out_path = output_dir / relative_path
        write_csv(out_path, rows)
        rel = str(out_path.relative_to(output_dir))
        outputs_created.append(rel)
        if "/normalized/" in rel:
            normalized_outputs.append(rel)
        else:
            reference_outputs.append(rel)

    # Legacy downstream compatibility: existing crossref code reads pr_lda_filings.csv.
    filings_src = output_dir / "outputs/normalized/lda/lda_filings.csv"
    legacy_filings = output_dir / "data/staging/processed/pr_lda_filings.csv"
    if filings_src.exists():
        legacy_filings.parent.mkdir(parents=True, exist_ok=True)
        legacy_filings.write_text(filings_src.read_text(encoding="utf-8"), encoding="utf-8")
        outputs_created.append(str(legacy_filings.relative_to(output_dir)))

    readiness = {
        "source_id": SOURCE_ID,
        "base_url": LDA_BASE_URL,
        "default_mode": "dry_run",
        "live_mode_requested": live,
        "api_key_required": False,
        "root_discovery_ok": root_discovery_ok,
        "endpoint_count": len(endpoints),
        "normalization_ok": normalization_ok,
        "raw_payload_stored": bool(include_raw),
        "outputs_created": outputs_created,
        "tests_passed": None,
        "blockers": blockers,
    }
    write_json(output_dir / "reports/lda_api_readiness.json", readiness)

    replacement = build_static_seed_report(output_dir, endpoints, normalized_outputs, reference_outputs, retrieved_at)
    write_json(output_dir / "reports/lda_static_seed_replacement_report.json", replacement)
    outputs_created.extend([
        "reports/lda_api_readiness.json",
        "reports/lda_static_seed_replacement_report.json",
    ])
    readiness["outputs_created"] = outputs_created
    write_json(output_dir / "reports/lda_api_readiness.json", readiness)
    write_checkpoint(output_dir, {"last_run_at": retrieved_at, "live": live, "outputs_created": outputs_created})
    return readiness


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch and normalize LDA.gov API data")
    parser.add_argument("--live", action="store_true", help="Perform live LDA.gov API calls. Default is dry-run fixture mode.")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Use synthetic fixtures and make no network calls. Default behavior.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum records per endpoint.")
    parser.add_argument("--output-dir", type=Path, default=Path("."), help="Repository root/output root.")
    parser.add_argument("--include-raw", action="store_true", help="Include raw JSON in CSV rows. Default false.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    readiness = run(output_dir=args.output_dir, live=bool(args.live), limit=args.limit, include_raw=bool(args.include_raw))
    print(json.dumps(readiness, indent=2, sort_keys=True))
    return 0 if not readiness["blockers"] else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
