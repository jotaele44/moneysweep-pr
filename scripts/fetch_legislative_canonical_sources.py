"""Fetch canonical legislative records for LegislaPR discovery candidates.

This script consumes the LegislaPR discovery probe output and attempts to attach
canonical evidence from OpenStates API v3 plus official Assembly/SUTRA document
links. It does not promote records unless both confirmation paths are present.

Usage:
  OPENSTATES_API_KEY=... python scripts/fetch_legislative_canonical_sources.py
  python scripts/fetch_legislative_canonical_sources.py --allow-missing-key
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from scripts.config import PROJECT_ROOT, setup_logging
except Exception:  # pragma: no cover
    PROJECT_ROOT = Path(__file__).resolve().parents[1]

    def setup_logging(name: str, log_dir: Path | None = None):
        import logging

        logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
        return logging.getLogger(name)


DEFAULT_INPUT = "data/staging/processed/pr_legislapr_measures_probe.json"
DEFAULT_OUTPUT = "data/staging/processed/pr_legislative_measures_canonical.json"
OPENSTATES_BASE = "https://v3.openstates.org"
OPENSTATES_JURISDICTION = "pr"
SOURCE_SYSTEM = "legislative_canonical_sources"


@dataclass(frozen=True)
class CanonicalLegislativeRecord:
    measure_id: str
    source_system: str
    legislapr_url: str
    openstates_url: str
    sutra_url: str
    openstates_bill_id: str
    openstates_session: str
    openstates_title: str
    openstates_classification: list[str]
    openstates_subjects: list[str]
    openstates_actions_count: int
    openstates_sponsorships_count: int
    official_document_confirmed: bool
    canonical_confirmation_status: str
    promotion_status: str
    fetched_at: str


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    if isinstance(value, tuple):
        return [str(item) for item in value if item is not None]
    return [str(value)]


def _compact_measure_id(value: str) -> str:
    raw = re.sub(r"[^A-Za-z0-9]", "", value or "").upper()
    raw = raw.replace("PDELC", "PC").replace("PDELS", "PS")
    return raw


def _spaced_measure_id(value: str) -> str:
    compact = _compact_measure_id(value)
    match = re.match(r"([A-Z]+)(\d+)$", compact)
    if not match:
        return value.strip()
    return f"{match.group(1)} {int(match.group(2))}"


def _read_json_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text.startswith("["):
        data = json.loads(text)
        return data if isinstance(data, list) else []
    rows = []
    for line in text.splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _url_exists(url: str, timeout: int = 20) -> bool:
    if not url:
        return False
    host = urlparse(url).netloc.lower()
    if not any(marker in host for marker in ["oslpr.org", "senado.pr.gov", "camara.pr.gov", "rcm.gov.pr"]):
        return False
    request = Request(url, method="HEAD", headers={"User-Agent": "MoneySweep-PR/1.0 canonical legislative confirmation"})
    try:
        with urlopen(request, timeout=timeout) as response:  # nosec: URL is constrained to official legislative domains
            return response.status < 400
    except HTTPError as exc:
        if exc.code in {403, 405}:
            try:
                request = Request(url, headers={"User-Agent": "MoneySweep-PR/1.0 canonical legislative confirmation"})
                with urlopen(request, timeout=timeout) as response:  # nosec: URL is constrained to official legislative domains
                    return response.status < 400
            except (HTTPError, URLError, TimeoutError, OSError):
                return False
        return False
    except (URLError, TimeoutError, OSError):
        return False


def _openstates_request(path: str, api_key: str, timeout: int = 30) -> dict[str, Any]:
    request = Request(
        f"{OPENSTATES_BASE}{path}",
        headers={
            "X-API-KEY": api_key,
            "User-Agent": "MoneySweep-PR/1.0 canonical legislative fetcher",
            "Accept": "application/json",
        },
    )
    with urlopen(request, timeout=timeout) as response:  # nosec: fixed OpenStates API host/path
        return json.loads(response.read().decode("utf-8"))


def _candidate_sessions(discovery_record: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ["openstates_session", "session"]:
        value = str(discovery_record.get(key) or "").strip()
        if value:
            values.append(value)
    openstates_url = str(discovery_record.get("openstates_url") or "")
    parts = [part for part in urlparse(openstates_url).path.split("/") if part]
    if "bills" in parts:
        idx = parts.index("bills")
        if idx + 1 < len(parts):
            values.append(parts[idx + 1])
    return _dedupe(values)


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        clean = str(value).strip()
        if clean and clean not in seen:
            out.append(clean)
            seen.add(clean)
    return out


def _extract_openstates_bill_payload(discovery_record: dict[str, Any], api_key: str) -> dict[str, Any]:
    measure_id = _spaced_measure_id(str(discovery_record.get("measure_id") or ""))
    compact_id = _compact_measure_id(measure_id)

    for session in _candidate_sessions(discovery_record):
        path = f"/bills/{OPENSTATES_JURISDICTION}/{quote(session, safe='')}/{quote(measure_id, safe='')}"
        try:
            return _openstates_request(path, api_key)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError):
            pass
        path = f"/bills/{OPENSTATES_JURISDICTION}/{quote(session, safe='')}/{quote(compact_id, safe='')}"
        try:
            return _openstates_request(path, api_key)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError):
            pass

    search_path = f"/bills?jurisdiction={OPENSTATES_JURISDICTION}&q={quote(compact_id, safe='')}"
    data = _openstates_request(search_path, api_key)
    results = data.get("results") or data.get("data") or []
    if isinstance(results, list):
        for item in results:
            item_id = _compact_measure_id(str(item.get("identifier") or item.get("id") or ""))
            if item_id == compact_id:
                return item
    return {}


def build_canonical_record(discovery_record: dict[str, Any], api_key: str | None) -> CanonicalLegislativeRecord:
    measure_id = _spaced_measure_id(str(discovery_record.get("measure_id") or ""))
    openstates_payload: dict[str, Any] = {}
    if api_key:
        openstates_payload = _extract_openstates_bill_payload(discovery_record, api_key)

    openstates_url = str(discovery_record.get("openstates_url") or "")
    sutra_url = str(discovery_record.get("sutra_url") or discovery_record.get("official_document_url") or "")
    official_document_confirmed = _url_exists(sutra_url)
    openstates_confirmed = bool(openstates_payload) or bool(openstates_url)

    if openstates_confirmed and official_document_confirmed:
        confirmation = "cross_confirmed"
        promotion = "promoted_candidate"
    elif openstates_confirmed or official_document_confirmed:
        confirmation = "partial_confirmation"
        promotion = "blocked_pending_canonical_confirmation"
    else:
        confirmation = "unconfirmed"
        promotion = "blocked_pending_canonical_confirmation"

    return CanonicalLegislativeRecord(
        measure_id=measure_id,
        source_system=SOURCE_SYSTEM,
        legislapr_url=str(discovery_record.get("source_url") or discovery_record.get("detail_url") or ""),
        openstates_url=openstates_url,
        sutra_url=sutra_url,
        openstates_bill_id=str(openstates_payload.get("id") or ""),
        openstates_session=str(openstates_payload.get("session") or discovery_record.get("session") or ""),
        openstates_title=str(openstates_payload.get("title") or discovery_record.get("title") or ""),
        openstates_classification=_as_string_list(openstates_payload.get("classification")),
        openstates_subjects=_as_string_list(openstates_payload.get("subject") or openstates_payload.get("subjects")),
        openstates_actions_count=len(openstates_payload.get("actions") or []),
        openstates_sponsorships_count=len(openstates_payload.get("sponsorships") or []),
        official_document_confirmed=official_document_confirmed,
        canonical_confirmation_status=confirmation,
        promotion_status=promotion,
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )


def run(
    root: Path | None = None,
    input_path: str = DEFAULT_INPUT,
    output_path: str = DEFAULT_OUTPUT,
    api_key: str | None = None,
    allow_missing_key: bool = False,
) -> dict[str, Any]:
    root = Path(root or PROJECT_ROOT)
    logger = setup_logging("fetch_legislative_canonical_sources", log_dir=root / "data" / "logs")
    api_key = api_key or os.environ.get("OPENSTATES_API_KEY")
    if not api_key and not allow_missing_key:
        raise RuntimeError("OPENSTATES_API_KEY is required unless --allow-missing-key is set")

    records = _read_json_records(root / input_path)
    canonical = [asdict(build_canonical_record(row, api_key)) for row in records]
    out = root / output_path
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(canonical, ensure_ascii=False, indent=2), encoding="utf-8")

    promoted = sum(1 for row in canonical if row["promotion_status"] == "promoted_candidate")
    logger.info("canonical legislative records: %s rows, %s promoted candidates", len(canonical), promoted)
    return {"status": "OK" if canonical else "EMPTY", "rows": len(canonical), "promoted_candidates": promoted, "output": str(out)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=DEFAULT_INPUT, help=f"Repo-relative discovery JSON/JSONL input path (default: {DEFAULT_INPUT})")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help=f"Repo-relative canonical JSON output path (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--allow-missing-key", action="store_true", help="Permit SUTRA-only confirmation when OPENSTATES_API_KEY is not available")
    args = parser.parse_args(argv)
    result = run(input_path=args.input, output_path=args.output, allow_missing_key=args.allow_missing_key)
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") in {"OK", "EMPTY"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
