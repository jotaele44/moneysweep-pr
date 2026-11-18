"""Acquire PRASA's official 2024 transition report of active contracts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pdfplumber
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.config import PROJECT_ROOT, setup_logging
from scripts.ingest_prasa import _run as ingest_prasa

SOURCE_URL = (
    "https://transicion2024.pr.gov/Agencias/163/Informe%20Contratos%20Vigentes/"
    "Contratos%20Vigentes%20al%2024%20de%20septiembre%20de%202024%20%28Informe%29.pdf"
)
EXPECTED_PAGES = 36
MIN_CONTRACT_ROWS = 100
CONTRACT_ID = re.compile(r"^\d{4}-\d{6}(?:-[A-Z0-9]+)?$")
RAW_COLUMNS = [
    "Número de Contrato",
    "Contratista",
    "Fecha de Adjudicación",
    "Fecha de Inicio",
    "Fecha de Terminación",
    "Monto",
    "Tipo de Contrato",
    "Descripción",
    "Estado",
    "source_url",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def clean_cell(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).replace("\u00a0", " ")).strip()


def normalize_header(value: Any) -> str:
    text = unicodedata.normalize("NFKD", clean_cell(value))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def canonical_header(value: Any) -> str:
    normalized = normalize_header(value)
    if "numero" in normalized and "contrato" in normalized:
        return "contract_id"
    if normalized == "contratista":
        return "vendor_name"
    if "fecha" in normalized and "otorg" in normalized:
        return "award_date"
    if "fecha" in normalized and "inicio" in normalized:
        return "start_date"
    if "fecha" in normalized and ("termin" in normalized or "fin" in normalized):
        return "end_date"
    if normalized in {"cuantia", "monto", "valor"}:
        return "amount"
    if "tipo" in normalized and "servicio" in normalized:
        return "contract_type"
    if normalized in {"comentarios", "comentario"}:
        return "description"
    return normalized


def normalize_amount(value: Any) -> str:
    text = clean_cell(value)
    if not text:
        return ""
    negative = text.startswith("(") and text.endswith(")")
    cleaned = re.sub(r"[^0-9.\-]", "", text)
    if negative and cleaned and not cleaned.startswith("-"):
        cleaned = "-" + cleaned
    return cleaned


def parse_extracted_table(table: list[list[Any]]) -> list[dict[str, str]]:
    required = {"contract_id", "vendor_name", "amount"}
    header_index = -1
    headers: list[str] = []
    for index, row in enumerate(table):
        candidate = [canonical_header(value) for value in row]
        if required.issubset(set(candidate)):
            header_index = index
            headers = candidate
            break
    if header_index < 0:
        return []

    rows: list[dict[str, str]] = []
    for row in table[header_index + 1 :]:
        values = {
            headers[index]: clean_cell(value)
            for index, value in enumerate(row)
            if index < len(headers) and headers[index]
        }
        contract_id = values.get("contract_id", "")
        vendor = values.get("vendor_name", "")
        if not CONTRACT_ID.fullmatch(contract_id) or not vendor:
            continue
        rows.append(
            {
                "Número de Contrato": contract_id,
                "Contratista": vendor,
                "Fecha de Adjudicación": values.get("award_date", ""),
                "Fecha de Inicio": values.get("start_date", ""),
                "Fecha de Terminación": values.get("end_date", ""),
                "Monto": normalize_amount(values.get("amount", "")),
                "Tipo de Contrato": values.get("contract_type", ""),
                "Descripción": values.get("description", ""),
                "Estado": "Vigente al 2024-09-24",
                "source_url": SOURCE_URL,
            }
        )
    return rows


def extract_pdf_contracts(pdf_bytes: bytes) -> dict[str, Any]:
    all_rows: list[dict[str, str]] = []
    pages_with_contracts = 0
    tables_seen = 0
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        page_count = len(pdf.pages)
        if page_count != EXPECTED_PAGES:
            raise RuntimeError(
                f"PRASA transition PDF page count changed: expected {EXPECTED_PAGES}, got {page_count}"
            )
        for page in pdf.pages:
            page_rows: list[dict[str, str]] = []
            for table in page.extract_tables():
                tables_seen += 1
                page_rows.extend(parse_extracted_table(table))
            if page_rows:
                pages_with_contracts += 1
                all_rows.extend(page_rows)

    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in all_rows:
        contract_id = row["Número de Contrato"]
        if contract_id in seen:
            continue
        seen.add(contract_id)
        deduped.append(row)

    if len(deduped) < MIN_CONTRACT_ROWS:
        raise RuntimeError(
            f"PRASA transition PDF extraction below floor: {len(deduped)} < {MIN_CONTRACT_ROWS}"
        )
    return {
        "rows": deduped,
        "page_count": page_count,
        "pages_with_contracts": pages_with_contracts,
        "tables_seen": tables_seen,
        "contract_rows": len(deduped),
    }


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RAW_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def run(root: Path | None = None, *, force: bool = False) -> dict[str, Any]:
    del (
        force
    )  # retained for producer compatibility; this fixed authoritative snapshot is re-fetched
    root = Path(root) if root is not None else PROJECT_ROOT
    logger = setup_logging("download_prasa_contracts")
    raw_dir = root / "data/raw/PRASA"
    pdf_path = raw_dir / "Contratos_Vigentes_2024-09-24.pdf"
    raw_csv = raw_dir / "Contratos_Vigentes_2024-09-24.csv"
    processed = root / "data/staging/processed/pr_prasa_contracts.csv"
    manifest_path = root / "data/manifests/prasa/contracts_vigentes_2024.json"
    manifest: dict[str, Any] = {
        "manifest_type": "prasa_official_transition_contracts",
        "source": "Puerto Rico 2024 Transition Portal - PRASA/AAA",
        "source_url": SOURCE_URL,
        "snapshot_as_of": "2024-09-24",
        "authentication": "public_none",
        "status": "running",
        "started_at": utc_now(),
        "expected_pages": EXPECTED_PAGES,
        "minimum_contract_rows": MIN_CONTRACT_ROWS,
    }
    write_json(manifest_path, manifest)

    try:
        response = requests.get(
            SOURCE_URL,
            headers={
                "User-Agent": "MoneySweep/1.0 public-source certification acquisition",
                "Accept": "application/pdf",
            },
            timeout=(10, 60),
        )
        response.raise_for_status()
        if not response.content.startswith(b"%PDF"):
            raise RuntimeError("PRASA transition source did not return a PDF")
        raw_dir.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(response.content)
        extracted = extract_pdf_contracts(response.content)
        write_csv(raw_csv, extracted["rows"])

        ingestion = ingest_prasa(root=root, force=True)
        processed_rows = int(ingestion.get("rows", 0))
        if processed_rows < 1 or not processed.exists():
            raise RuntimeError("Official PRASA transition ingestion produced no processed rows")

        manifest.update(
            {
                "status": "complete",
                "completed_at": utc_now(),
                "http_status": response.status_code,
                "content_type": response.headers.get("Content-Type", ""),
                "page_count": extracted["page_count"],
                "pages_with_contracts": extracted["pages_with_contracts"],
                "tables_seen": extracted["tables_seen"],
                "contract_rows": extracted["contract_rows"],
                "processed_rows": processed_rows,
                "artifacts": {
                    "raw_pdf": {
                        "path": str(pdf_path.relative_to(root)),
                        "bytes": pdf_path.stat().st_size,
                        "sha256": sha256_file(pdf_path),
                    },
                    "raw_csv": {
                        "path": str(raw_csv.relative_to(root)),
                        "bytes": raw_csv.stat().st_size,
                        "sha256": sha256_file(raw_csv),
                    },
                    "processed_csv": {
                        "path": str(processed.relative_to(root)),
                        "bytes": processed.stat().st_size,
                        "sha256": sha256_file(processed),
                    },
                },
            }
        )
        write_json(manifest_path, manifest)
        logger.info(
            "Acquired %s PRASA contracts from the official %s-page transition report",
            extracted["contract_rows"],
            extracted["page_count"],
        )
        return manifest
    except Exception as exc:
        manifest.update(
            {
                "status": "failed",
                "completed_at": utc_now(),
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
        if pdf_path.exists():
            manifest["raw_pdf_sha256"] = sha256_file(pdf_path)
        write_json(manifest_path, manifest)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    report = run(args.root, force=args.force)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("status") == "complete" and report.get("processed_rows", 0) > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
