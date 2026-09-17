#!/usr/bin/env python3
"""Acquire and byte-freeze the JP macro workbooks required by VECTOR_C.

Inputs come from ``jp_public_exhaustion_v1.json``. The downloader preserves
source URL, response headers, retrieval UTC, exact bytes, byte size, and SHA256.
It fails closed unless the response is a valid ZIP/XLSX manifestation. It never
marks a failed retrieval as source absence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile

import requests

DEFAULT_MANIFEST = Path("data/manifests/macro/jp_public_exhaustion_v1.json")
USER_AGENT = "MoneySweep-V2-Public-Source-Audit/1.0"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_filename(source_id: str) -> str:
    return source_id.lower().replace("jp_", "") + ".xlsx"


def _validate_xlsx(data: bytes) -> None:
    if not data.startswith(b"PK"):
        raise ValueError("response is not a ZIP/XLSX byte stream")
    try:
        from io import BytesIO

        with ZipFile(BytesIO(data)) as archive:
            names = set(archive.namelist())
            required = {"[Content_Types].xml", "xl/workbook.xml"}
            missing = sorted(required - names)
            if missing:
                raise ValueError(f"response ZIP lacks required XLSX members: {missing}")
    except BadZipFile as exc:
        raise ValueError("response is not a valid ZIP/XLSX archive") from exc


def acquire_one(
    source: dict[str, Any],
    out_dir: Path,
    *,
    session: Any = requests,
    timeout: int = 60,
) -> dict[str, Any]:
    source_id = str(source["id"])
    url = str(source["url"])
    retrieved_utc = datetime.now(timezone.utc).isoformat()
    response = session.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/octet-stream;q=0.9,*/*;q=0.1"},
        timeout=timeout,
        allow_redirects=True,
    )
    response.raise_for_status()
    data = bytes(response.content)
    _validate_xlsx(data)

    raw_dir = out_dir / "raw"
    header_dir = out_dir / "headers"
    raw_dir.mkdir(parents=True, exist_ok=True)
    header_dir.mkdir(parents=True, exist_ok=True)

    filename = _safe_filename(source_id)
    raw_path = raw_dir / filename
    headers_path = header_dir / f"{filename}.headers.json"
    raw_path.write_bytes(data)
    headers = {str(key): str(value) for key, value in response.headers.items()}
    headers_path.write_text(json.dumps(headers, indent=2, sort_keys=True), encoding="utf-8")

    return {
        "source_id": source_id,
        "source_title": source.get("title"),
        "source_url": url,
        "resolved_url": str(getattr(response, "url", url)),
        "retrieved_utc": retrieved_utc,
        "path": str(raw_path),
        "response_headers_path": str(headers_path),
        "content_type": headers.get("Content-Type") or headers.get("content-type"),
        "size_bytes": len(data),
        "sha256": _sha256(data),
        "state": "BYTE_FROZEN",
    }


def acquire_all(
    manifest_path: Path,
    out_dir: Path,
    *,
    session: Any = requests,
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sources = manifest.get("mandatory_workbooks", [])
    if not sources:
        raise ValueError("manifest contains no mandatory_workbooks")

    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for source in sources:
        try:
            results.append(acquire_one(source, out_dir, session=session))
        except Exception as exc:
            failures.append(
                {
                    "source_id": str(source.get("id")),
                    "source_url": str(source.get("url")),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "state": "RETRIEVAL_BLOCKED_NOT_SOURCE_ABSENT",
                }
            )

    payload = {
        "snapshot_version": "1.0",
        "source_manifest": str(manifest_path),
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "expected_count": len(sources),
        "frozen_count": len(results),
        "failure_count": len(failures),
        "complete": len(results) == len(sources) and not failures,
        "artifacts": results,
        "failures": failures,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "source_manifest.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    payload = acquire_all(args.manifest, args.out_dir)
    print(json.dumps({key: payload[key] for key in ("expected_count", "frozen_count", "failure_count", "complete")}, indent=2))
    return 0 if payload["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
