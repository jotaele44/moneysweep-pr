"""Acquire Puerto Rico's official Department of Justice lobbyist registry."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from lxml import html as lxml_html

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.config import PROJECT_ROOT, setup_logging
from scripts.ingest_cabilderos import _run as ingest_cabilderos

REGISTRY_URL = "https://registrodecabilderos.pr.gov/Lobbyist/Details"
RAW_COLUMNS = [
    "lobbyist_name",
    "client_name",
    "registration_year",
    "registro_cabildero_num",
    "authorized_personnel",
    "certificate_url",
    "source_url",
]
REGISTRATION_YEAR = re.compile(r"^(20\d{2})Q[1-4]-")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_header(value: str) -> str:
    text = str(value or "").replace("(s)", "s").replace("(S)", "S")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^A-Za-z0-9]+", " ", text).strip().lower()
    return re.sub(r"\s+", " ", text)


def canonical_header(value: str) -> str:
    normalized = normalize_header(value)
    if normalized == "nombre":
        return "lobbyist_name"
    if "numero" in normalized and "registro" in normalized:
        return "registro_cabildero_num"
    if normalized.startswith("cliente"):
        return "client_name"
    if "personal" in normalized and "autorizado" in normalized:
        return "authorized_personnel"
    return normalized


def cell_text(node: Any) -> str:
    return " ".join(part.strip() for part in node.itertext() if part.strip()).strip()


def parse_registry_html(html_text: str) -> dict[str, Any]:
    document = lxml_html.fromstring(html_text)
    required = {"lobbyist_name", "registro_cabildero_num", "client_name"}
    selected_rows: list[Any] | None = None
    selected_headers: list[str] | None = None
    header_index = -1

    for table in document.xpath("//table"):
        rows = table.xpath(".//tr")
        for index, row in enumerate(rows):
            cells = row.xpath("./th|./td")
            headers = [canonical_header(cell_text(cell)) for cell in cells]
            if required.issubset(set(headers)):
                selected_rows = rows
                selected_headers = headers
                header_index = index
                break
        if selected_rows is not None:
            break

    if selected_rows is None or selected_headers is None:
        raise RuntimeError("Official cabilderos table with expected headers was not found")

    raw_rows: list[dict[str, str]] = []
    registry_rows = 0
    registrations: set[str] = set()
    lobbyists: set[str] = set()
    client_relationships = 0

    for row in selected_rows[header_index + 1 :]:
        cells = row.xpath("./td|./th")
        if not cells:
            continue
        values = {
            selected_headers[index]: cell_text(cell)
            for index, cell in enumerate(cells)
            if index < len(selected_headers)
        }
        lobbyist = values.get("lobbyist_name", "").strip()
        registration = values.get("registro_cabildero_num", "").strip()
        clients_text = values.get("client_name", "").strip()
        personnel = values.get("authorized_personnel", "").strip()
        if not lobbyist or not registration:
            continue

        registry_rows += 1
        registrations.add(registration)
        lobbyists.add(lobbyist)
        year_match = REGISTRATION_YEAR.match(registration)
        registration_year = year_match.group(1) if year_match else ""
        links = [str(value).strip() for value in row.xpath(".//a/@href") if str(value).strip()]
        certificate_href = next(
            (value for value in links if "/Lobbyist/Certify/" in value),
            "",
        )
        certificate_url = urljoin(REGISTRY_URL, certificate_href) if certificate_href else ""
        clients = [item.strip() for item in clients_text.split(";") if item.strip()]

        if clients:
            client_relationships += len(clients)
            for client in clients:
                raw_rows.append(
                    {
                        "lobbyist_name": lobbyist,
                        "client_name": client,
                        "registration_year": registration_year,
                        "registro_cabildero_num": registration,
                        "authorized_personnel": personnel,
                        "certificate_url": certificate_url,
                        "source_url": REGISTRY_URL,
                    }
                )
        else:
            raw_rows.append(
                {
                    "lobbyist_name": lobbyist,
                    "client_name": "",
                    "registration_year": registration_year,
                    "registro_cabildero_num": registration,
                    "authorized_personnel": personnel,
                    "certificate_url": certificate_url,
                    "source_url": REGISTRY_URL,
                }
            )

    if registry_rows < 1:
        raise RuntimeError("Official cabilderos registry parsed zero registrations")
    if client_relationships < 1:
        raise RuntimeError("Official cabilderos registry parsed zero lobbyist-client relationships")

    return {
        "rows": raw_rows,
        "registry_rows": registry_rows,
        "raw_csv_rows": len(raw_rows),
        "client_relationships": client_relationships,
        "unique_registrations": len(registrations),
        "unique_lobbyists": len(lobbyists),
        "headers": selected_headers,
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
    del force  # retained for producer/CLI compatibility; authoritative acquisition always refreshes
    root = Path(root) if root is not None else PROJECT_ROOT
    logger = setup_logging("download_cabilderos")
    raw_dir = root / "data/raw/Cabilderos"
    html_path = raw_dir / "justice_registry.html"
    raw_csv = raw_dir / "justice_registry.csv"
    processed = root / "data/staging/processed/pr_cabilderos.csv"
    manifest_path = root / "data/manifests/cabilderos/justice_registry_latest.json"
    started_at = utc_now()

    manifest: dict[str, Any] = {
        "manifest_type": "pr_justice_cabilderos_acquisition",
        "source": "Puerto Rico Department of Justice - Registro de Cabilderos",
        "source_url": REGISTRY_URL,
        "authentication": "public_none",
        "started_at": started_at,
        "status": "running",
    }
    write_json(manifest_path, manifest)

    try:
        response = requests.get(
            REGISTRY_URL,
            headers={
                "User-Agent": "MoneySweep/1.0 public-source certification acquisition",
                "Accept": "text/html,application/xhtml+xml",
            },
            timeout=(10, 45),
        )
        response.raise_for_status()
        raw_dir.mkdir(parents=True, exist_ok=True)
        html_path.write_bytes(response.content)
        parsed = parse_registry_html(response.text)
        write_csv(raw_csv, parsed["rows"])

        ingestion = ingest_cabilderos(root=root, force=True)
        processed_rows = int(ingestion.get("rows", 0))
        if processed_rows < 1 or not processed.exists():
            raise RuntimeError("Official cabilderos ingestion produced no processed rows")

        manifest.update(
            {
                "status": "complete",
                "completed_at": utc_now(),
                "http_status": response.status_code,
                "content_type": response.headers.get("Content-Type", ""),
                "registry_rows": parsed["registry_rows"],
                "unique_registrations": parsed["unique_registrations"],
                "unique_lobbyists": parsed["unique_lobbyists"],
                "client_relationships": parsed["client_relationships"],
                "raw_csv_rows": parsed["raw_csv_rows"],
                "processed_rows": processed_rows,
                "parsed_headers": parsed["headers"],
                "artifacts": {
                    "raw_html": {
                        "path": str(html_path.relative_to(root)),
                        "bytes": html_path.stat().st_size,
                        "sha256": sha256_file(html_path),
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
            "Acquired %s Justice registry rows / %s lobbyist-client relationships / %s processed rows",
            parsed["registry_rows"],
            parsed["client_relationships"],
            processed_rows,
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
        if html_path.exists():
            manifest["raw_html_sha256"] = sha256_file(html_path)
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
