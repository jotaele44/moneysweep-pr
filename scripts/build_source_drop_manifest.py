#!/usr/bin/env python3
"""Build and optionally stage the MoneySweep external source-drop manifest.

The manifest records externally supplied evidence without treating source-file
contents as instructions. Use --stage to copy selected files into the existing
repo dropzones before running the normal ingestion scripts.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
# Operator-local evidence root. Absolute by nature: these are files on the
# operator's own machine, not repository content. Overridable so the script
# is runnable from any checkout -- without the override it resolves nothing
# outside one specific machine, and every inspected path reports UNRESOLVED.
FINANCIALS = Path(
    os.environ.get("MONEYSWEEP_FINANCIALS_ROOT", "/Users/jotaele/Documents/Financials")
)

DROP_SOURCES: list[dict[str, Any]] = [
    {
        "source_id": "fema_pa_openfema_v2",
        "classification": "FOUND",
        "inclusion_decision": "manifest_only_existing_processed_input",
        "path": FINANCIALS
        / "COR3_Recovery/contractdata/data/staging/processed/pr_fema_pa_master.csv",
        "target_relpath": None,
        "blocker": "COR3/FEMA recovery evidence found; existing producer output shape.",
    },
    {
        "source_id": "hud_cdbg_dr_public",
        "classification": "FOUND",
        "inclusion_decision": "manifest_only_existing_processed_input",
        "path": FINANCIALS
        / "COR3_Recovery/contractdata/data/staging/processed/pr_cdbg_dr_master.csv",
        "target_relpath": None,
        "blocker": "Public CDBG-DR evidence found; not equivalent to authorized DRGR.",
    },
    {
        "source_id": "hud_cdbg_dr_public",
        "classification": "FOUND",
        "inclusion_decision": "manifest_only_raw_support",
        "path": FINANCIALS
        / "COR3_Recovery/contractdata/data/staging/raw/cdbg_dr/cdbg_dr_usaspending.csv",
        "target_relpath": None,
        "blocker": "Raw CDBG-DR USAspending support.",
    },
    *[
        {
            "source_id": "cor3",
            "classification": "FOUND",
            "inclusion_decision": "stage_for_existing_dropzone",
            "path": FINANCIALS / "COR3 Data" / name,
            "target_relpath": f"data/raw/COR3/{name}",
            "blocker": "COR3 workbook found; filename mismatch is recorded, not hidden.",
        }
        for name in (
            "COR3 PA_110726_0836.xlsx",
            "COR3 HMGP_110726_0836.xlsx",
            "COR3 DISBURSEMENT_110726_0824.xlsx",
            "COR3 Procurement Inventory_110726_0841.xlsx",
            "COR3 RFP and Contracts_110726_0810.xlsx",
        )
    ],
    {
        "source_id": "pr_cabilderos",
        "classification": "FOUND",
        "inclusion_decision": "stage_for_existing_dropzone",
        "path": FINANCIALS / "Consolidated/contracts/pr_lda_filings.csv",
        "target_relpath": "data/raw/Cabilderos/pr_lda_filings.csv",
        "blocker": "Cabilderos/LDA rows found; registry-specific identity still downstream.",
    },
    {
        "source_id": "oficina_contralor",
        "classification": "FOUND",
        "inclusion_decision": "stage_for_existing_dropzone",
        "path": FINANCIALS / "Consolidated/contracts/pr_contralor_audits.csv",
        "target_relpath": "data/raw/Oficina del Contralor/pr_contralor_audits.csv",
        "blocker": "Contralor audit rows found.",
    },
    {
        "source_id": "oce",
        "classification": "FOUND",
        "inclusion_decision": "stage_for_existing_dropzone",
        "path": FINANCIALS / "Consolidated/financial/pr_oce_donations.csv",
        "target_relpath": "data/raw/OCE/pr_oce_donations.csv",
        "blocker": "OCE donation rows found.",
    },
    {
        "source_id": "donaciones",
        "classification": "FOUND",
        "inclusion_decision": "stage_for_existing_dropzone",
        "path": FINANCIALS / "Consolidated/financial/pr_donaciones.csv",
        "target_relpath": "data/raw/Donaciones/pr_donaciones.csv",
        "blocker": "CEE/CEEPUR donation rows found.",
    },
    {
        "source_id": "prasa",
        "classification": "SUPERSEDED_PARTIAL",
        "inclusion_decision": "manifest_only_superseded_header_only",
        "path": FINANCIALS / "Documents/contractdata/data/staging/processed/pr_prasa_contracts.csv",
        "target_relpath": None,
        "blocker": "External legacy PRASA contract master is header-only; superseded by the ACT agency 163 transition contract PDF parser.",
    },
    {
        "source_id": "prasa",
        "classification": "FOUND",
        "inclusion_decision": "parse_authoritative_transition_pdf",
        "path": FINANCIALS
        / "2024/ACT/transicion2024_archive/files/by_agency/163/Informe_de_Contratos_Vigentes/Contratos_Vigentes_al_24_de_septiembre_de_2024_Informe.pdf",
        "target_relpath": None,
        "blocker": "Authoritative PRASA transition contract PDF parsed into pr_prasa_contracts.csv and prasa_contracts_master.csv.",
        "generated_outputs": [
            "data/staging/processed/pr_prasa_contracts.csv",
            "data/staging/processed/prasa_contracts_master.csv",
        ],
    },
    {
        "source_id": "prasa",
        "classification": "FOUND_SUPPORTING",
        "inclusion_decision": "manifest_only_documentary_support",
        "path": FINANCIALS / "2024/CER/FY2024 PRASA CER_Final.pdf",
        "target_relpath": None,
        "blocker": "PRASA CER support exists; not the contract source, but no longer holds the source blocker open.",
    },
    {
        "source_id": "prasa",
        "classification": "FOUND_SUPPORTING",
        "inclusion_decision": "manifest_only_documentary_support",
        "path": FINANCIALS
        / "2024/ACT/transicion2024_archive/files/by_agency/163/Informe_Inventario_de_Propiedad/Inventario_Activos_AAA_hasta_2024.xlsx",
        "target_relpath": None,
        "blocker": "PRASA asset inventory exists; not the contract source, but no longer holds the source blocker open.",
    },
    {
        "source_id": "hud_drgr_authorized",
        "classification": "PARTIAL_UNRESOLVED",
        "inclusion_decision": "manifest_only_not_authorized_export",
        "path": FINANCIALS / "Documents/contractdata/data/normalized/hud_drgr_projects.parquet",
        "target_relpath": None,
        "blocker": "DRGR-shaped artifact is zero-row and does not prove authorized export delivery.",
    },
    {
        "source_id": "hud_drgr_authorized",
        "classification": "PARTIAL_UNRESOLVED",
        "inclusion_decision": "manifest_only_not_authorized_export",
        "path": FINANCIALS
        / "Documents/contractdata/data/normalized/hud_drgr_responsible_orgs_resolved.parquet",
        "target_relpath": None,
        "blocker": "DRGR responsible-org artifact is zero-row and does not prove authorized export delivery.",
    },
    {
        "source_id": "hud_drgr_authorized",
        "classification": "PARTIAL_UNRESOLVED",
        "inclusion_decision": "manifest_only_not_authorized_export",
        "path": FINANCIALS / "Documents/contractdata/data/staging/processed/pr_hud_hcv.csv",
        "target_relpath": None,
        "blocker": "HUD HCV/Section 8 rows exist; this is not an authorized DRGR activity/project export.",
    },
]


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_csv(path: Path) -> dict[str, Any]:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                reader = csv.reader(handle)
                header = next(reader, [])
                rows = sum(1 for _ in reader)
            return {"format": "csv", "encoding": encoding, "logical_rows": rows, "header": header}
        except UnicodeDecodeError:
            continue
    return {"format": "csv", "error": "decode_failed", "logical_rows": None, "header": []}


def inspect_xlsx(path: Path) -> dict[str, Any]:
    try:
        import pandas as pd

        xl = pd.ExcelFile(path)
        sheets = []
        for sheet in xl.sheet_names:
            df = xl.parse(sheet, dtype=str, nrows=0)
            rows = len(xl.parse(sheet, dtype=str, usecols=df.columns))
            sheets.append(
                {"name": sheet, "logical_rows": rows, "header": [str(c) for c in df.columns]}
            )
        return {"format": "xlsx", "sheets": sheets}
    except Exception as exc:  # noqa: BLE001
        return {"format": "xlsx", "error": f"{type(exc).__name__}: {exc}"}


def inspect_path(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False}
    info: dict[str, Any] = {
        "exists": True,
        "byte_size": path.stat().st_size,
        "sha256": sha256_file(path),
    }
    suffix = path.suffix.lower()
    if suffix == ".csv":
        info.update(inspect_csv(path))
    elif suffix in {".xlsx", ".xls"}:
        info.update(inspect_xlsx(path))
    elif suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            info.update(
                {
                    "format": "zip",
                    "member_count": len(archive.infolist()),
                    "members": [
                        {"path": m.filename, "uncompressed_size": m.file_size}
                        for m in archive.infolist()[:100]
                    ],
                }
            )
    else:
        info["format"] = suffix.lstrip(".") or "unknown"
    return info


def build_records(stage: bool) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in DROP_SOURCES:
        path = Path(item["path"])
        target_relpath = item["target_relpath"]
        target_path = REPO_ROOT / target_relpath if target_relpath else None
        staged = False
        if stage and target_path and path.is_file():
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if not target_path.exists() or sha256_file(path) != sha256_file(target_path):
                shutil.copy2(path, target_path)
            staged = True
        records.append(
            {
                "source_id": item["source_id"],
                "classification": item["classification"],
                "inclusion_decision": item["inclusion_decision"],
                "blocker_classification_note": item["blocker"],
                "absolute_source_path": str(path),
                "target_relpath": target_relpath or "",
                "target_sha256": sha256_file(target_path)
                if target_path and target_path.exists()
                else None,
                "generated_outputs": item.get("generated_outputs", []),
                "staged": staged,
                "raw_normalized_canonical_policy": "Preserve raw source strings; normalization and canonical identity are downstream only.",
                **inspect_path(path),
            }
        )
    return records


def write_outputs(records: list[dict[str, Any]], out_dir: Path, *, stage: bool) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "producer": "moneysweep-pr",
        "generated_at": utc_now(),
        "lumen_status": "unavailable_in_session",
        "stage_requested": stage,
        "records": records,
        "arithmetic": {
            "total": len(records),
            "found": sum(1 for r in records if r["classification"].startswith("FOUND")),
            "partial_or_unresolved": sum(
                1 for r in records if not r["classification"].startswith("FOUND")
            ),
            "missing_files": sum(1 for r in records if not r.get("exists")),
            "staged": sum(1 for r in records if r.get("staged")),
        },
    }
    (out_dir / "moneysweep_source_drop_manifest.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    fields = [
        "source_id",
        "classification",
        "inclusion_decision",
        "absolute_source_path",
        "target_relpath",
        "exists",
        "byte_size",
        "sha256",
        "logical_rows",
        "staged",
        "blocker_classification_note",
    ]
    with (out_dir / "moneysweep_source_drop_manifest.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(records)
    print(json.dumps(payload["arithmetic"], sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stage", action="store_true", help="Copy stageable evidence into repo dropzones"
    )
    parser.add_argument("--out-dir", default=str(REPO_ROOT / "reports" / "source_drops"))
    args = parser.parse_args()
    write_outputs(build_records(stage=args.stage), Path(args.out_dir), stage=args.stage)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
