from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from moneysweep.capital_control import (
    SEC13FMaterializationTarget,
    SECFairAccessClient,
    SECRequestPolicy,
    SECUserAgent,
    materialize_sec_13f,
)


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid ISO date: {value!r}") from exc


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".part",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, indent=2, sort_keys=True, default=str)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze a complete SEC Form 13F primary XML + information-table XML pair and "
            "reconcile primary-declared row/value totals against parsed source rows."
        )
    )
    parser.add_argument("--accession", required=True)
    parser.add_argument("--filer-cik", required=True)
    parser.add_argument("--filing-date", required=True, type=_parse_date)
    parser.add_argument("--period-of-report", required=True, type=_parse_date)
    parser.add_argument("--primary-url", required=True)
    parser.add_argument("--information-table-url", required=True)
    parser.add_argument("--expected-primary-size", required=True, type=int)
    parser.add_argument("--expected-information-table-size", required=True, type=int)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--application", default="MoneySweepPR/0.2")
    parser.add_argument("--contact", required=True)
    parser.add_argument("--value-scale", type=float, default=1.0)
    parser.add_argument(
        "--canonicality",
        choices=("CANONICAL", "NONCANONICAL"),
        default="CANONICAL",
    )
    parser.add_argument("--max-requests-per-second", type=float, default=5.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    target = SEC13FMaterializationTarget(
        accession_number=args.accession,
        filer_cik=args.filer_cik,
        filing_date=args.filing_date,
        period_of_report=args.period_of_report,
        primary_document_url=args.primary_url,
        information_table_url=args.information_table_url,
        value_scale=args.value_scale,
        expected_primary_size=args.expected_primary_size,
        expected_information_table_size=args.expected_information_table_size,
        canonicality=args.canonicality,
    )
    client = SECFairAccessClient(
        SECUserAgent(args.application, args.contact),
        policy=SECRequestPolicy(max_requests_per_second=args.max_requests_per_second),
    )
    result = materialize_sec_13f(client, target, args.output_dir)

    payload: dict[str, Any] = {
        "accession_number": result.target.accession_number,
        "filer_cik": result.target.filer_cik,
        "filing_date": result.target.filing_date.isoformat(),
        "period_of_report": result.target.period_of_report.isoformat(),
        "certification_status": result.certification_status,
        "primary_document": {
            "path": str(result.primary_resource.path),
            "write_status": result.primary_resource.write_status,
            "request_url": result.primary_resource.receipt.request_url,
            "response_url": result.primary_resource.receipt.response_url,
            "retrieval_utc": result.primary_resource.receipt.retrieval_utc.isoformat(),
            "byte_size": result.primary_resource.receipt.byte_size,
            "sha256": result.primary_sha256,
        },
        "information_table": {
            "path": str(result.information_table_resource.path),
            "write_status": result.information_table_resource.write_status,
            "request_url": result.information_table_resource.receipt.request_url,
            "response_url": result.information_table_resource.receipt.response_url,
            "retrieval_utc": result.information_table_resource.receipt.retrieval_utc.isoformat(),
            "byte_size": result.information_table_resource.receipt.byte_size,
            "sha256": result.information_table_sha256,
        },
        "reconciliation": {
            "declared_table_entry_total": result.declared_table_entry_total,
            "parsed_table_entry_total": result.parsed_table_entry_total,
            "declared_table_value_total": str(result.declared_table_value_total),
            "parsed_table_value_total": str(result.parsed_table_value_total),
        },
        "source_manifest": result.source_manifest,
    }
    report_path = args.output_dir / "materialization.json"
    _write_json_atomic(report_path, payload)
    print(json.dumps(payload, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
