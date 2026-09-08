#!/usr/bin/env python3
"""Audit local HUD/DRGR-shaped evidence for authorized DRGR export closure.

The gate is intentionally conservative: public CDBG-DR, HCV, ACT transition
documents, and zero-row DRGR-shaped artifacts are receipt evidence, but they do
not close ``hud_drgr_authorized`` unless non-empty DRGR activity/project/drawdown
tables are present.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FINANCIALS = Path("/Users/jotaele/Documents/Financials")
DEFAULT_REPORT_ROOT = Path("reports/live-readiness")

KNOWN_PATHS = [
    FINANCIALS / "COR3_Recovery/contractdata/data/staging/processed/pr_cdbg_dr_master.csv",
    FINANCIALS / "COR3_Recovery/contractdata/data/staging/raw/cdbg_dr/cdbg_dr_usaspending.csv",
    FINANCIALS
    / "2024/ACT/transicion2024_archive/files/by_agency/078/Informe_de_Contratos_Vigentes/Informe_de_Contratos_Vigentes-Programa_de_CDBG-DR-MIT.pdf",
    FINANCIALS
    / "2024/ACT/transicion2024_archive/files/by_agency/078/Informe_Inventario_de_Propiedad/Informe_de_Inventario_de_Propiedad_CDBG-DR-MIT_-_Flota.pdf",
    FINANCIALS
    / "2024/ACT/transicion2024_archive/files/by_agency/078/Informe_de_Subastas/Informe_de_Subastas_en_Proceso_y_Adjudicadas_-_CDBG-DR-MIT.pdf",
    FINANCIALS
    / "2024/ACT/transicion2024_archive/files/by_agency/078/Informe_Acciones_Judiciales/Informe_Acciones_Judiciales_CDBG-DR-MIT.pdf",
    FINANCIALS / "Documents/contractdata/data/staging/processed/pr_hud_hcv.csv",
    FINANCIALS / "Documents/contractdata/data/normalized/hud_drgr_projects.parquet",
    FINANCIALS
    / "Documents/contractdata/data/normalized/hud_drgr_responsible_orgs_resolved.parquet",
]

AUTHORIZED_TABLE_HINTS = {
    "activity": ("activity id", "activity number", "activity name"),
    "project": ("project id", "project number", "project name"),
    "drawdown": ("drawdown", "voucher", "draw amount"),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_csv(path: Path, raw: bytes | None = None) -> dict[str, Any]:
    raw = path.read_bytes() if raw is None else raw
    encoding = "utf-8-sig"
    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError:
        # Single-byte decoding is reversible but the intended encoding is unknown.
        encoding = "latin-1"
        text = raw.decode(encoding)
    candidates = []
    hints_set = {hint for hints in AUTHORIZED_TABLE_HINTS.values() for hint in hints}
    for delimiter in (",", ";", "\t", "|"):
        try:
            rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True))
        except csv.Error:
            continue
        for index, row in enumerate(rows[:100]):
            normalized = [value.strip().lower().replace("_", " ") for value in row]
            if len(row) > 1 and hints_set.intersection(normalized):
                candidates.append((delimiter, index, rows, normalized))
                break
    if len(candidates) != 1:
        return {
            "format": "csv",
            "encoding": encoding,
            "logical_rows": None,
            "header": [],
            "authorized_table_hints": [],
            "error": "header_or_delimiter_unresolved",
            "schema_state": "UNRESOLVED",
        }
    delimiter, index, rows, normalized = candidates[0]
    header = rows[index]
    data_rows = rows[index + 1 :]
    blank_rows = sum(not any(value.strip() for value in row) for row in data_rows)
    retained = [row for row in data_rows if any(value.strip() for value in row)]
    malformed = sum(len(row) != len(header) for row in retained)
    duplicates = sorted({value for value in normalized if normalized.count(value) > 1})
    valid = not malformed and not duplicates and all(normalized)
    hinted = sorted(
        table
        for table, hints in AUTHORIZED_TABLE_HINTS.items()
        if set(hints).intersection(normalized)
    )
    return {
        "format": "csv",
        "encoding": encoding,
        "encoding_state": "KNOWN_UTF8" if encoding == "utf-8-sig" else "UNRESOLVED_SINGLE_BYTE",
        "delimiter": delimiter,
        "header_record": index + 1,
        "preamble": rows[:index],
        "logical_rows": len(retained),
        "header": header,
        "schema_mapping": [
            {"raw": raw_name, "normalized": name} for raw_name, name in zip(header, normalized)
        ],
        "duplicate_normalized_fields": duplicates,
        "row_arithmetic": {
            "source": len(data_rows),
            "retained": len(retained),
            "excluded_blank": blank_rows,
            "malformed": malformed,
        },
        "schema_state": "PASS" if valid else "UNRESOLVED",
        "authorized_table_hints": hinted if valid else [],
    }


def inspect_parquet(path: Path, raw: bytes | None = None) -> dict[str, Any]:
    try:
        import pandas as pd

        frame = pd.read_parquet(io.BytesIO(raw) if raw is not None else path)
        header = [str(column) for column in frame.columns]
        header_text = " ".join(header).lower()
        hinted = sorted(
            table
            for table, hints in AUTHORIZED_TABLE_HINTS.items()
            if any(hint in header_text for hint in hints)
        )
        return {
            "format": "parquet",
            "logical_rows": len(frame),
            "header": header,
            "authorized_table_hints": hinted,
        }
    except Exception as exc:  # noqa: BLE001
        return {"format": "parquet", "logical_rows": None, "header": [], "error": str(exc)}


def inspect_path(path: Path, snapshot_dir: Path | None = None) -> dict[str, Any]:
    if not path.is_file():
        return {
            "path": str(path),
            "exists": path.exists(),
            "classification": "UNRESOLVED",
            "inclusion_decision": "preserve_blocker",
            "error": "not_a_readable_file",
        }
    try:
        raw = path.read_bytes()
    except OSError:
        return {
            "path": str(path),
            "exists": True,
            "classification": "UNRESOLVED",
            "inclusion_decision": "preserve_blocker",
            "error": "source_unreadable",
        }
    digest = hashlib.sha256(raw).hexdigest()
    record: dict[str, Any] = {
        "path": str(path),
        "exists": True,
        "byte_size": len(raw),
        "sha256": digest,
        "identity_effect": "NONE",
        "authorization": "UNPROVEN",
    }
    if snapshot_dir is not None:
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        target = snapshot_dir / digest
        if target.exists():
            if target.read_bytes() != raw:
                raise ValueError("snapshot digest collision or corrupted stored bytes")
        else:
            with target.open("xb") as handle:
                handle.write(raw)
        record["snapshot_relative_path"] = "inputs/" + digest
    suffix = path.suffix.lower()
    if suffix == ".csv":
        record.update(inspect_csv(path, raw))
    elif suffix == ".parquet":
        record.update(inspect_parquet(path, raw))
    elif suffix == ".pdf":
        record.update({"format": "pdf", "logical_rows": None, "header": []})
    else:
        record.update({"format": suffix.lstrip(".") or "unknown", "logical_rows": None})

    path_text = str(path).lower()
    rows = record.get("logical_rows")
    hints = record.get("authorized_table_hints") or []
    if suffix in {".csv", ".parquet"} and rows and hints and "hcv" not in path_text:
        record["classification"] = "FOUND_AUTHORIZED_CANDIDATE"
        record["inclusion_decision"] = "eligible_for_hud_drgr_ingest_review"
    elif "hcv" in path_text:
        record["classification"] = "PARTIAL_NOT_AUTHORIZED_DRGR"
        record["inclusion_decision"] = "exclude_from_authorized_drgr_credit"
    elif "cdbg" in path_text or suffix == ".pdf":
        record["classification"] = "FOUND_SUPPORTING_NOT_AUTHORIZED_EXPORT"
        record["inclusion_decision"] = "documentary_support_only"
    else:
        record["classification"] = "PARTIAL_UNRESOLVED"
        record["inclusion_decision"] = "preserve_blocker"
    return record


def build_receipt(report_dir: Path) -> dict[str, Any]:
    receipt_path = report_dir / "hud_drgr_authorized_pursuit_receipt.json"
    if receipt_path.exists():
        raise FileExistsError("Use a new report directory to preserve the prior source snapshot")
    records = [inspect_path(path, report_dir / "inputs") for path in KNOWN_PATHS]
    authorized = [r for r in records if r.get("classification") == "FOUND_AUTHORIZED_CANDIDATE"]
    receipt = {
        "receipt_type": "moneysweep_hud_drgr_authorized_pursuit",
        "generated_at_utc": utc_now(),
        "source_id": "hud_drgr_authorized",
        "lumen_status": "LUMEN_UNAVAILABLE_OR_UNHEALTHY; bounded local inspection used",
        "classification_counts": {
            state: sum(1 for row in records if row.get("classification") == state)
            for state in sorted({str(row.get("classification")) for row in records})
        },
        "arithmetic": {
            "total": len(records),
            "classified": sum(1 for row in records if row.get("classification")),
            "authorized_candidates": len(authorized),
        },
        "records": records,
        "result_state": "FOUND_AUTHORIZED_CANDIDATE" if authorized else "PARTIAL_UNRESOLVED",
        "authorization": "UNPROVEN",
        "identity_effect": "NONE",
        "discovery_scope": "EXPLICIT_PATH_LIST_NOT_EXHAUSTIVE",
        "blocker": "No authorized HUD DRGR export is proven; candidates require independent authorization and ingestion review.",
    }
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "hud_drgr_authorized_pursuit_receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with (report_dir / "hud_drgr_authorized_pursuit_summary.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "path",
                "exists",
                "format",
                "logical_rows",
                "classification",
                "inclusion_decision",
                "sha256",
            ],
        )
        writer.writeheader()
        for row in records:
            writer.writerow({field: row.get(field) for field in writer.fieldnames})
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", default=None)
    args = parser.parse_args(argv)
    report_dir = (
        Path(args.report_dir) if args.report_dir else DEFAULT_REPORT_ROOT / "hud_drgr_pursuit"
    )
    receipt = build_receipt(report_dir)
    print(json.dumps({k: receipt[k] for k in ("result_state", "arithmetic", "blocker")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
