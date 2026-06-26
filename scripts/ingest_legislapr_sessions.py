"""Ingest LegislaPR/OpenStates session references from discovery records.

The script builds a compact session index from LegislaPR discovery output,
OpenStates URLs, and optional operator-supplied session IDs. It does not call
external services; it creates a deterministic staging artifact for downstream
canonical fetches.

Usage:
  python scripts/ingest_legislapr_sessions.py
  python scripts/ingest_legislapr_sessions.py --session 2025-2028
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

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
DEFAULT_OUTPUT = "data/staging/processed/pr_legislapr_sessions.json"
SESSION_RE = re.compile(r"\b(?:19|20)\d{2}\s*-\s*(?:19|20)\d{2}\b")


@dataclass(frozen=True)
class LegislativeSessionRecord:
    session_id: str
    jurisdiction: str
    source_system: str
    source_records: int
    first_seen_url: str
    extraction_method: str
    ingestion_timestamp: str


def _read_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text.startswith("["):
        data = json.loads(text)
        return data if isinstance(data, list) else []
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _session_from_openstates_url(url: str) -> str:
    parts = [part for part in urlparse(url or "").path.split("/") if part]
    if "bills" in parts:
        idx = parts.index("bills")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return ""


def _normalize_session(value: str) -> str:
    value = re.sub(r"\s+", "", value or "")
    match = SESSION_RE.search(value.replace("-", " - "))
    if match:
        return match.group(0).replace(" ", "")
    return value.strip()


def extract_sessions(records: Iterable[dict[str, Any]], manual_sessions: Iterable[str] = ()) -> list[LegislativeSessionRecord]:
    buckets: dict[str, dict[str, Any]] = {}
    now = datetime.now(timezone.utc).isoformat()

    def add(session_id: str, source_url: str, method: str) -> None:
        session = _normalize_session(session_id)
        if not session:
            return
        bucket = buckets.setdefault(
            session,
            {
                "source_records": 0,
                "first_seen_url": source_url,
                "extraction_method": method,
            },
        )
        bucket["source_records"] += 1
        if not bucket.get("first_seen_url") and source_url:
            bucket["first_seen_url"] = source_url

    for row in records:
        source_url = str(row.get("source_url") or row.get("detail_url") or "")
        session = str(row.get("openstates_session") or row.get("session") or "")
        add(session, source_url, "record_field")
        add(_session_from_openstates_url(str(row.get("openstates_url") or "")), source_url, "openstates_url")
        for value in SESSION_RE.findall(json.dumps(row, ensure_ascii=False)):
            add(value, source_url, "text_scan")

    for session in manual_sessions:
        add(session, "", "operator_supplied")

    return [
        LegislativeSessionRecord(
            session_id=session,
            jurisdiction="pr",
            source_system="legislapr_discovery",
            source_records=int(data["source_records"]),
            first_seen_url=str(data.get("first_seen_url") or ""),
            extraction_method=str(data.get("extraction_method") or ""),
            ingestion_timestamp=now,
        )
        for session, data in sorted(buckets.items())
    ]


def run(root: Path | None = None, input_path: str = DEFAULT_INPUT, output_path: str = DEFAULT_OUTPUT, manual_sessions: Iterable[str] = ()) -> dict[str, Any]:
    root = Path(root or PROJECT_ROOT)
    logger = setup_logging("ingest_legislapr_sessions", log_dir=root / "data" / "logs")
    records = _read_records(root / input_path)
    sessions = extract_sessions(records, manual_sessions=manual_sessions)
    out = root / output_path
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps([asdict(row) for row in sessions], ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("LegislaPR sessions: %s rows", len(sessions))
    return {"status": "OK" if sessions else "EMPTY", "rows": len(sessions), "output": str(out)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=DEFAULT_INPUT)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--session", action="append", default=[])
    args = parser.parse_args(argv)
    print(json.dumps(run(input_path=args.input, output_path=args.output, manual_sessions=args.session), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
