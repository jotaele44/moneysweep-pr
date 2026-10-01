"""Parse the PRASA 2024 transition contract PDF into the PRASA contract table.

The source is the ACT transition agency 163 "Contratos Vigentes" report. This
parser is intentionally narrow: it accepts the stable layout-preserving text
shape of that report and writes the existing ``pr_prasa_contracts.csv`` schema.
It does not claim that arbitrary PRASA PDFs are machine-readable contract feeds.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.config import PROJECT_ROOT, setup_logging
from scripts.ingest_prasa import PRASA_COLUMNS, _normalize_name

DEFAULT_SOURCE = Path(
    "/Users/jotaele/Documents/Financials/2024/ACT/transicion2024_archive/files/by_agency/163/"
    "Informe_de_Contratos_Vigentes/Contratos_Vigentes_al_24_de_septiembre_de_2024_Informe.pdf"
)

CONTRACT_RE = re.compile(
    r"^(?P<contract_id>\d{4}-\d{6}(?:-[A-Z])?)\s+"
    r"(?P<vendor_name>.+?)\s+"
    r"(?P<award_date>\d{1,2}[-/][A-Za-zÁÉÍÓÚáéíóúñÑ.]+[-/]\d{2,4})\s+"
    r"(?P<start_date>\d{1,2}[-/][A-Za-zÁÉÍÓÚáéíóúñÑ.]+[-/]\d{2,4})\s+"
    r"(?P<end_date>\d{1,2}[-/][A-Za-zÁÉÍÓÚáéíóúñÑ.]+[-/]\d{2,4})\s+"
    r"(?P<tail>.*)$"
)
AMOUNT_RE = re.compile(r"(?P<amount>-?\$?[\d,]+(?:\.\d{2})?)\s*(?P<service>.*)$")
SKIP_PREFIXES = (
    "CONTRATOS VIGENTES",
    "RADICADOS",
    "Número de",
    "Contrato",
    "Contratista",
    "Fecha de",
    "Otorgación",
    "Inicio",
    "Terminación",
    "Cuantía",
    "Tipo de Servicio",
    "Comentarios",
    "Art. 9",
    "Autoridad de Acueductos",
    "Transición Gubernamental",
)
SERVICE_PREFIXES = (
    "Construcción",
    "Servicio",
    "Servicios",
    "Sistema",
    "Compra",
    "Acuerdo",
    "Arrendamiento",
    "Limpieza",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pdf_text(path: Path) -> str:
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", str(path), "-"],
            capture_output=True,
            check=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError:
        with pdfplumber.open(path) as pdf:
            return "\n".join(page.extract_text(layout=True) or "" for page in pdf.pages)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"pdftotext failed for {path}: {exc.stderr}") from exc
    return result.stdout


def _split_tail(tail: str, prefixes: list[str]) -> tuple[str, str]:
    service_prefix = " ".join(
        part for part in prefixes if part.startswith(SERVICE_PREFIXES)
    ).strip()
    amount_match = AMOUNT_RE.search(tail.strip())
    if not amount_match:
        return "", " ".join(part for part in [service_prefix, tail.strip()] if part).strip()
    service = " ".join(
        part for part in [service_prefix, amount_match.group("service").strip()] if part
    ).strip()
    return amount_match.group("amount").strip(), service


def parse_prasa_transition_contracts(source: Path = DEFAULT_SOURCE) -> tuple[pd.DataFrame, dict]:
    text = _pdf_text(source)
    rows = []
    carry_lines: list[str] = []
    rejected_lines = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            carry_lines = []
            continue
        if line.startswith(SKIP_PREFIXES) or re.fullmatch(r"\d+", line):
            continue

        match = CONTRACT_RE.match(line)
        if match:
            data = match.groupdict()
            vendor_prefix = " ".join(
                part for part in carry_lines if not part.startswith(SERVICE_PREFIXES)
            ).strip()
            amount, service = _split_tail(data.pop("tail"), carry_lines)
            vendor_name = " ".join(
                part for part in [vendor_prefix, data["vendor_name"].strip()] if part
            ).strip()
            rows.append(
                {
                    "contract_id": data["contract_id"],
                    "vendor_name": vendor_name,
                    "vendor_normalized": _normalize_name(vendor_name),
                    "contract_type": service,
                    "contract_value": amount,
                    "award_date": data["award_date"],
                    "start_date": data["start_date"],
                    "end_date": data["end_date"],
                    "status": "vigente",
                    "description": service,
                    "municipality": "",
                    "source_file": str(source),
                }
            )
            carry_lines = []
            continue

        if re.match(r"^-?\$|^\d{1,2}[-/]", line):
            rejected_lines.append(line)
        else:
            carry_lines.append(line)

    frame = pd.DataFrame(rows, columns=PRASA_COLUMNS)
    receipt = {
        "schema_version": "moneysweep_prasa_transition_contracts_ingest_v1",
        "generated_at_utc": _utc_now(),
        "source_path": str(source),
        "source_sha256": _sha256(source),
        "source_bytes": source.stat().st_size,
        "rows_parsed": len(frame),
        "unique_contract_ids": int(frame["contract_id"].nunique()) if not frame.empty else 0,
        "duplicate_contract_ids": int(len(frame) - frame["contract_id"].nunique())
        if not frame.empty
        else 0,
        "rejected_line_count": len(rejected_lines),
        "rejected_line_samples": rejected_lines[:20],
        "parser_scope": "ACT agency 163 PRASA 2024 transition Contratos Vigentes PDF only",
        "classification": "FOUND_STRUCTURED_FROM_AUTHORITY_TRANSITION_PDF",
        "raw_canonical_separation": "Original PDF remains outside repo; generated CSV stores source path and hash.",
    }
    return frame, receipt


def run(source: Path = DEFAULT_SOURCE, root: Path = PROJECT_ROOT, force: bool = False) -> dict:
    logger = setup_logging("ingest_prasa_transition_contracts")
    if not source.exists():
        raise FileNotFoundError(f"PRASA transition contract source not found: {source}")

    out_path = root / "data" / "staging" / "processed" / "pr_prasa_contracts.csv"
    receipt_path = (
        root
        / "data"
        / "manifests"
        / "prasa"
        / f"{_utc_now().replace(':', '').replace('-', '')}.transition_contracts.json"
    )
    if out_path.exists() and not force:
        existing = pd.read_csv(out_path, dtype=str, na_filter=False, low_memory=False)
        if not existing.empty:
            logger.info("  pr_prasa_contracts.csv already has data; use --force to replace it.")
            return {"rows": len(existing), "path": str(out_path), "receipt": None, "skipped": True}

    frame, receipt = parse_prasa_transition_contracts(source)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(out_path, index=False, encoding="utf-8")
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(
        json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    logger.info("  Parsed %s PRASA transition contract rows", len(frame))
    return {
        "rows": len(frame),
        "path": str(out_path),
        "receipt": str(receipt_path),
        "skipped": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest PRASA transition contract PDF")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = run(source=args.source, force=args.force)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
