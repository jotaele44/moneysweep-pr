"""Prepare uploaded analysis-master CSVs for reproducible federation export.

This command converts the three raw calibration/input masters used during the
local production run into moneysweep-pr canonical processed files:

* entities_resolved.csv
* contracts_master.csv
* financial_flows_master.csv
* entity_edges.csv

The output directory can then be passed directly to ``scripts/run_export.py``.
No network calls are made and the mapping is deterministic.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from moneysweep.runtime.name_normalization import normalize_name  # noqa: E402

ENTITY_FIELDS = [
    "entity_id",
    "entity_name",
    "normalized_name",
    "entity_type",
    "entity_uei",
    "parent_uei",
    "match_confidence",
    "resolution_method",
    "source_files",
]

CONTRACT_FIELDS = [
    "source_system",
    "recipient_name",
    "normalized_name",
    "recipient_uei",
    "awarding_agency",
    "funding_source",
    "obligation_amount",
    "award_date",
    "fiscal_year",
    "link_confidence",
    "municipality",
    "geo_municipality_name",
    "geo_municipality_code",
    "geo_lat",
    "geo_lon",
    "geo_attribution_source",
    "geo_attribution_confidence",
]

FLOW_FIELDS = [
    "source_system",
    "recipient_entity_id",
    "funding_source",
    "amount",
    "flow_date",
    "link_confidence",
    "municipality",
    "geo_municipality_name",
    "geo_municipality_code",
    "geo_lat",
    "geo_lon",
    "geo_attribution_source",
    "geo_attribution_confidence",
]

EDGE_FIELDS = ["source", "target", "edge_type", "source_dataset", "confidence"]


def _clean(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).strip()


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, fields: list[str], rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def _stable_id(prefix: str, *parts: Any) -> str:
    payload = "|".join(_clean(p).upper() for p in parts if _clean(p))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def _norm(*values: Any) -> str:
    for value in values:
        raw = _clean(value)
        if raw:
            return normalize_name(raw)
    return "UNKNOWN"


def _date_or_fiscal_year(raw_date: Any, fiscal_year: Any) -> str:
    raw = _clean(raw_date)
    if raw:
        head = raw.split("T", 1)[0].split(" ", 1)[0]
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(head, fmt).strftime("%Y-%m-%d")
            except ValueError:
                pass
    fy = _clean(fiscal_year)
    if fy:
        try:
            year = int(float(fy))
            return f"{year}-07-01"
        except ValueError:
            pass
    return "1970-01-01"


def _amount(value: Any) -> str:
    raw = _clean(value).replace("$", "").replace(",", "")
    if not raw:
        return "0"
    try:
        amount = float(raw)
    except ValueError:
        return "0"
    if not math.isfinite(amount) or amount < 0:
        return "0"
    return str(amount)


def _entity_key(name: str, uei: str = "") -> tuple[str, str]:
    norm = _norm(name)
    entity_id = _stable_id("upload_ent", uei or norm)
    return entity_id, norm


def _add_entity(
    entities: dict[str, dict[str, str]],
    name: Any,
    *,
    uei: Any = "",
    source: str,
    entity_type: str = "organization",
) -> str:
    raw_name = _clean(name)
    if not raw_name:
        raw_name = "UNKNOWN"
    entity_id, norm = _entity_key(raw_name, _clean(uei))
    entities.setdefault(
        entity_id,
        {
            "entity_id": entity_id,
            "entity_name": raw_name,
            "normalized_name": norm,
            "entity_type": entity_type,
            "entity_uei": _clean(uei),
            "parent_uei": "",
            "match_confidence": "0.9" if raw_name != "UNKNOWN" else "0.5",
            "resolution_method": "uploaded_master_schema_mapping",
            "source_files": source,
        },
    )
    return entity_id


def prepare_uploaded_masters(
    contracts_master: str | Path,
    awards_master: str | Path,
    lda_summary: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    contracts_master = Path(contracts_master)
    awards_master = Path(awards_master)
    lda_summary = Path(lda_summary)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    contracts_rows = _read_csv(contracts_master)
    awards_rows = _read_csv(awards_master)
    lda_rows = _read_csv(lda_summary)

    entities: dict[str, dict[str, str]] = {}
    canonical_contracts: list[dict[str, str]] = []
    flows: list[dict[str, str]] = []
    edges: list[dict[str, str]] = []

    # Awards master -> funding_awards input.
    for row in awards_rows:
        recipient = _clean(row.get("recipient_name")) or "UNKNOWN"
        recipient_norm = _clean(row.get("recipient_name_normalized")) or _norm(recipient)
        agency = (
            _clean(row.get("awarding_agency"))
            or _clean(row.get("awarding_sub_agency"))
            or "UNKNOWN AGENCY"
        )
        _add_entity(
            entities,
            recipient_norm or recipient,
            uei=row.get("recipient_uei"),
            source=awards_master.name,
        )
        _add_entity(entities, agency, source=awards_master.name, entity_type="funding_agency")
        municipality = _clean(row.get("pop_county"))
        fy = _clean(row.get("fiscal_year"))
        canonical_contracts.append(
            {
                "source_system": _clean(row.get("source_dataset")) or "uploaded_awards_master",
                "recipient_name": recipient,
                "normalized_name": recipient_norm,
                "recipient_uei": _clean(row.get("recipient_uei")),
                "awarding_agency": agency,
                "funding_source": _clean(row.get("award_category"))
                or _clean(row.get("source_dataset"))
                or "award",
                "obligation_amount": _amount(row.get("obligated_amount")),
                "award_date": _date_or_fiscal_year(row.get("award_date"), fy),
                "fiscal_year": fy or "1970",
                "link_confidence": "0.85",
                "municipality": municipality,
                "geo_municipality_name": municipality,
                "geo_municipality_code": "",
                "geo_lat": "",
                "geo_lon": "",
                "geo_attribution_source": "uploaded_awards_master.pop_county"
                if municipality
                else "",
                "geo_attribution_confidence": "0.6" if municipality else "",
            }
        )
        edges.append(
            {
                "source": recipient_norm,
                "target": _norm(agency),
                "edge_type": "award_recipient",
                "source_dataset": _clean(row.get("source_dataset")) or "uploaded_awards_master",
                "confidence": "0.85",
            }
        )

    # Contract master -> financial_flows input; preserves local production run behavior.
    for row in contracts_rows:
        vendor = _clean(row.get("normalized_vendor")) or _clean(row.get("vendor_name")) or "UNKNOWN"
        agency = (
            _clean(row.get("normalized_agency"))
            or _clean(row.get("agency_name"))
            or "UNKNOWN AGENCY"
        )
        vendor_id = _add_entity(
            entities, vendor, uei=row.get("recipient_uei"), source=contracts_master.name
        )
        _add_entity(entities, agency, source=contracts_master.name, entity_type="funding_agency")
        fy = _clean(row.get("fiscal_year"))
        flows.append(
            {
                "source_system": _clean(row.get("dataset")) or "uploaded_contracts_master",
                "recipient_entity_id": vendor_id,
                "funding_source": agency,
                "amount": _amount(row.get("amount_usd") or row.get("total_obligated")),
                "flow_date": _date_or_fiscal_year(row.get("award_date"), fy),
                "link_confidence": "0.9"
                if _clean(row.get("evidence_tier")).startswith("T1")
                else "0.75",
                "municipality": "",
                "geo_municipality_name": "",
                "geo_municipality_code": "",
                "geo_lat": "",
                "geo_lon": "",
                "geo_attribution_source": "",
                "geo_attribution_confidence": "",
            }
        )
        edges.append(
            {
                "source": vendor,
                "target": agency,
                "edge_type": "contract_awarded_by",
                "source_dataset": _clean(row.get("dataset")) or "uploaded_contracts_master",
                "confidence": "0.85",
            }
        )

    # LDA summary -> financial_flows context input.
    for row in lda_rows:
        client = _clean(row.get("canonical_client")) or "UNKNOWN"
        client_id = _add_entity(entities, client, source=lda_summary.name)
        flows.append(
            {
                "source_system": "uploaded_lda_summary",
                "recipient_entity_id": client_id,
                "funding_source": "LOBBYING DISCLOSURE ACT",
                "amount": _amount(row.get("total_lobbying_amount")),
                "flow_date": _date_or_fiscal_year("", row.get("last_year")),
                "link_confidence": "0.7",
                "municipality": "",
                "geo_municipality_name": "",
                "geo_municipality_code": "",
                "geo_lat": "",
                "geo_lon": "",
                "geo_attribution_source": "",
                "geo_attribution_confidence": "",
            }
        )
        edges.append(
            {
                "source": client,
                "target": "LOBBYING DISCLOSURE ACT",
                "edge_type": "lobbying_client_context",
                "source_dataset": "uploaded_lda_summary",
                "confidence": "0.7",
            }
        )
        _add_entity(
            entities,
            "LOBBYING DISCLOSURE ACT",
            source=lda_summary.name,
            entity_type="funding_agency",
        )

    counts = {
        "entities_resolved.csv": _write_csv(
            output_dir / "entities_resolved.csv", ENTITY_FIELDS, entities.values()
        ),
        "contracts_master.csv": _write_csv(
            output_dir / "contracts_master.csv", CONTRACT_FIELDS, canonical_contracts
        ),
        "financial_flows_master.csv": _write_csv(
            output_dir / "financial_flows_master.csv", FLOW_FIELDS, flows
        ),
        "entity_edges.csv": _write_csv(output_dir / "entity_edges.csv", EDGE_FIELDS, edges),
    }
    report = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "output_dir": str(output_dir),
        "inputs": {
            "contracts_master": str(contracts_master),
            "awards_master": str(awards_master),
            "lda_summary": str(lda_summary),
        },
        "input_rows": {
            "contracts_master": len(contracts_rows),
            "awards_master": len(awards_rows),
            "lda_summary": len(lda_rows),
        },
        "output_rows": counts,
    }
    (output_dir / "uploaded_master_mapping_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Map uploaded raw masters into canonical processed export inputs."
    )
    parser.add_argument("--contracts-master", required=True, help="pr_contracts_master_v2 CSV")
    parser.add_argument("--awards-master", required=True, help="pr_all_awards_master CSV")
    parser.add_argument("--lda-summary", required=True, help="lda_canonical_client_summary_all CSV")
    parser.add_argument("--output-dir", required=True, help="Canonical processed output directory")
    args = parser.parse_args(argv)
    report = prepare_uploaded_masters(
        args.contracts_master, args.awards_master, args.lda_summary, args.output_dir
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
