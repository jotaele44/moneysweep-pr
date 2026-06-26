"""Build MoneySweep legislative link candidates.

Links legislative measures to fiscal entities using conservative keyword and
agency-name matching. Output is a review queue, not a promoted fact table.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable
import logging

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from scripts.config import PROJECT_ROOT, setup_logging
except Exception:  # pragma: no cover
    PROJECT_ROOT = Path(__file__).resolve().parents[1]

    def setup_logging(log_name: str, log_dir: Path | None = None) -> logging.Logger:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
        return logging.getLogger(log_name)


DEFAULT_MEASURES = "data/staging/processed/pr_legislapr_measures_probe.json"
DEFAULT_CONTRACTS = "data/staging/processed/pr_contracts_master.csv"
DEFAULT_OUTPUT = "data/staging/processed/pr_legislative_fiscal_link_candidates.csv"
FISCAL_TERMS = (
    "fondos",
    "presupuesto",
    "asignacion",
    "asignación",
    "contrato",
    "emergencia",
    "reembolso",
    "incentivo",
    "bonos",
    "deuda",
    "fema",
    "cor3",
    "cdbg",
)


def norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def read_json_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text.startswith("["):
        data = json.loads(text)
        return data if isinstance(data, list) else []
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def read_contracts(path: Path, limit: int = 5000) -> list[dict[str, str]]:
    if not path.exists():
        return []
    rows: list[dict[str, str]] = []
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        reader = csv.DictReader(handle)
        for idx, row in enumerate(reader):
            if idx >= limit:
                break
            rows.append({key: str(value or "") for key, value in row.items()})
    return rows


def fiscal_terms(text: str) -> list[str]:
    normalized = norm(text)
    return [term for term in FISCAL_TERMS if norm(term) in normalized]


def build_links(
    measures: Iterable[dict[str, Any]], contracts: Iterable[dict[str, str]]
) -> list[dict[str, str]]:
    contract_rows = list(contracts)
    links: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for measure in measures:
        measure_id = str(measure.get("measure_id") or "")
        text = " ".join(
            str(measure.get(key) or "") for key in ["title", "summary", "status", "source_url"]
        )
        terms = fiscal_terms(text)
        if not terms and not measure.get("fiscal_language_detected"):
            continue
        measure_text = norm(text)
        for contract in contract_rows:
            agency = contract.get("awarding_agency") or contract.get("agency") or ""
            municipality = (
                contract.get("municipality") or contract.get("geo_municipality_name") or ""
            )
            award_id = contract.get("award_id") or contract.get("contract_number") or ""
            signals: list[str] = []
            if agency and norm(agency) and norm(agency) in measure_text:
                signals.append("agency_name")
            if municipality and norm(municipality) and norm(municipality) in measure_text:
                signals.append("municipality_name")
            if terms:
                signals.append("fiscal_terms")
            if not signals:
                continue
            key = (measure_id, award_id, "+".join(sorted(set(signals))))
            if key in seen:
                continue
            seen.add(key)
            links.append(
                {
                    "measure_id": measure_id,
                    "target_award_id": award_id,
                    "target_agency": agency,
                    "target_municipality": municipality,
                    "link_type": "legislative_fiscal_candidate",
                    "evidence_signals": "+".join(sorted(set(signals))),
                    "fiscal_terms": "+".join(terms),
                    "link_confidence": "0.50"
                    if "agency_name" in signals or "municipality_name" in signals
                    else "0.25",
                    "review_status": "manual_review_required",
                    "source_url": str(measure.get("source_url") or ""),
                }
            )
    return links


def run(
    root: Path | None = None,
    measures_path: str = DEFAULT_MEASURES,
    contracts_path: str = DEFAULT_CONTRACTS,
    output_path: str = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    root = Path(root or PROJECT_ROOT)
    logger = setup_logging("build_legislative_links", log_dir=root / "data" / "logs")
    links = build_links(
        read_json_records(root / measures_path), read_contracts(root / contracts_path)
    )
    out = root / output_path
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "measure_id",
                "target_award_id",
                "target_agency",
                "target_municipality",
                "link_type",
                "evidence_signals",
                "fiscal_terms",
                "link_confidence",
                "review_status",
                "source_url",
            ],
        )
        writer.writeheader()
        writer.writerows(links)
    logger.info("legislative fiscal link candidates: %s rows", len(links))
    return {"status": "OK" if links else "EMPTY", "rows": len(links), "output": str(out)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--measures", default=DEFAULT_MEASURES)
    parser.add_argument("--contracts", default=DEFAULT_CONTRACTS)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    print(
        json.dumps(
            run(
                measures_path=args.measures, contracts_path=args.contracts, output_path=args.output
            ),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
