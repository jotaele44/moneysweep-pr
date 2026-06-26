"""Build an OpenStates-to-OSL/SUTRA legislative crosswalk.

Consumes LegislaPR discovery records and canonical confirmation records, then
emits a deterministic crosswalk keyed by Puerto Rico measure ID. No network calls
are performed here; this is a link-builder and provenance-normalization stage.

Usage:
  python scripts/build_osl_sutra_crosswalk.py
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

DEFAULT_DISCOVERY = "data/staging/processed/pr_legislapr_measures_probe.json"
DEFAULT_CANONICAL = "data/staging/processed/pr_legislative_measures_canonical.json"
DEFAULT_OUTPUT = "data/staging/processed/pr_osl_sutra_crosswalk.json"
OFFICIAL_HOST_MARKERS = ("oslpr.org", "senado.pr.gov", "camara.pr.gov", "rcm.gov.pr")


@dataclass(frozen=True)
class LegislativeCrosswalkRecord:
    measure_id: str
    measure_compact_id: str
    legislapr_url: str
    openstates_url: str
    sutra_url: str
    official_host: str
    canonical_confirmation_status: str
    promotion_status: str
    link_confidence: float
    source_system: str
    ingestion_timestamp: str


def compact_measure_id(value: str) -> str:
    raw = re.sub(r"[^A-Za-z0-9]", "", value or "").upper()
    raw = raw.replace("PDELC", "PC").replace("PDELS", "PS")
    return raw


def spaced_measure_id(value: str) -> str:
    compact = compact_measure_id(value)
    match = re.match(r"([A-Z]+)(\d+)$", compact)
    if not match:
        return str(value or "").strip()
    return f"{match.group(1)} {int(match.group(2))}"


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


def _official_host(url: str) -> str:
    host = urlparse(url or "").netloc.lower()
    if any(marker in host for marker in OFFICIAL_HOST_MARKERS):
        return host
    return ""


def _confidence(openstates_url: str, sutra_url: str, status: str) -> float:
    score = 0.10
    if openstates_url:
        score += 0.35
    if _official_host(sutra_url):
        score += 0.35
    if status in {"cross_confirmed", "promoted_candidate"}:
        score += 0.20
    return round(min(score, 1.0), 2)


def build_crosswalk(discovery: Iterable[dict[str, Any]], canonical: Iterable[dict[str, Any]]) -> list[LegislativeCrosswalkRecord]:
    rows: dict[str, dict[str, Any]] = {}
    for record in discovery:
        mid = compact_measure_id(str(record.get("measure_id") or ""))
        if not mid:
            continue
        rows.setdefault(mid, {}).update(
            {
                "measure_id": spaced_measure_id(mid),
                "legislapr_url": str(record.get("source_url") or record.get("detail_url") or ""),
                "openstates_url": str(record.get("openstates_url") or ""),
                "sutra_url": str(record.get("sutra_url") or record.get("official_document_url") or ""),
                "canonical_confirmation_status": str(record.get("canonical_confirmation_status") or ""),
                "promotion_status": str(record.get("promotion_status") or ""),
            }
        )
    for record in canonical:
        mid = compact_measure_id(str(record.get("measure_id") or ""))
        if not mid:
            continue
        base = rows.setdefault(mid, {"measure_id": spaced_measure_id(mid)})
        for key in ["legislapr_url", "openstates_url", "sutra_url", "canonical_confirmation_status", "promotion_status"]:
            value = str(record.get(key) or "")
            if value:
                base[key] = value

    now = datetime.now(timezone.utc).isoformat()
    output: list[LegislativeCrosswalkRecord] = []
    for mid, record in sorted(rows.items()):
        openstates_url = str(record.get("openstates_url") or "")
        sutra_url = str(record.get("sutra_url") or "")
        status = str(record.get("canonical_confirmation_status") or "")
        promotion = str(record.get("promotion_status") or "")
        output.append(
            LegislativeCrosswalkRecord(
                measure_id=str(record.get("measure_id") or spaced_measure_id(mid)),
                measure_compact_id=mid,
                legislapr_url=str(record.get("legislapr_url") or ""),
                openstates_url=openstates_url,
                sutra_url=sutra_url,
                official_host=_official_host(sutra_url),
                canonical_confirmation_status=status,
                promotion_status=promotion,
                link_confidence=_confidence(openstates_url, sutra_url, status or promotion),
                source_system="osl_sutra_crosswalk",
                ingestion_timestamp=now,
            )
        )
    return output


def run(
    root: Path | None = None,
    discovery_path: str = DEFAULT_DISCOVERY,
    canonical_path: str = DEFAULT_CANONICAL,
    output_path: str = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    root = Path(root or PROJECT_ROOT)
    logger = setup_logging("build_osl_sutra_crosswalk", log_dir=root / "data" / "logs")
    rows = build_crosswalk(_read_records(root / discovery_path), _read_records(root / canonical_path))
    out = root / output_path
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps([asdict(row) for row in rows], ensure_ascii=False, indent=2), encoding="utf-8")
    confirmed = sum(1 for row in rows if row.link_confidence >= 0.8)
    logger.info("OSL/SUTRA crosswalk: %s rows, %s high-confidence", len(rows), confirmed)
    return {"status": "OK" if rows else "EMPTY", "rows": len(rows), "high_confidence_rows": confirmed, "output": str(out)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--discovery", default=DEFAULT_DISCOVERY)
    parser.add_argument("--canonical", default=DEFAULT_CANONICAL)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    print(json.dumps(run(discovery_path=args.discovery, canonical_path=args.canonical, output_path=args.output), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
