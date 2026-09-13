from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

from .source_adapter import (
    FrozenSEC13FAdapter,
    SEC13FFilingMetadata,
    SECAcquisitionError,
    SECFairAccessClient,
    SECFrozenResource,
)


@dataclass(frozen=True)
class SEC13FMaterializationTarget:
    accession_number: str
    filer_cik: str
    filing_date: date
    period_of_report: date
    primary_document_url: str
    information_table_url: str
    value_scale: float = 1.0
    expected_primary_size: int | None = None
    expected_information_table_size: int | None = None
    canonicality: str = "NONCANONICAL"


@dataclass(frozen=True)
class SEC13FMaterializationResult:
    target: SEC13FMaterializationTarget
    primary_resource: SECFrozenResource
    information_table_resource: SECFrozenResource
    primary_sha256: str
    information_table_sha256: str
    declared_table_entry_total: int
    parsed_table_entry_total: int
    declared_table_value_total: Decimal
    parsed_table_value_total: Decimal
    source_manifest: dict[str, object]
    certification_status: str


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find_text(root: ET.Element, local_name: str) -> str | None:
    for element in root.iter():
        if _local_name(element.tag) == local_name and element.text is not None:
            value = element.text.strip()
            if value:
                return value
    return None


def _positive_int(raw: str | None, field: str) -> int:
    if raw is None:
        raise SECAcquisitionError(f"primary 13F document missing {field}")
    try:
        value = int(raw)
    except ValueError as exc:
        raise SECAcquisitionError(f"primary 13F document has invalid {field}: {raw!r}") from exc
    if value <= 0:
        raise SECAcquisitionError(f"primary 13F document {field} must be positive")
    return value


def _nonnegative_decimal(raw: str | None, field: str) -> Decimal:
    if raw is None:
        raise SECAcquisitionError(f"primary 13F document missing {field}")
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise SECAcquisitionError(f"primary 13F document has invalid {field}: {raw!r}") from exc
    if value < 0:
        raise SECAcquisitionError(f"primary 13F document {field} must be nonnegative")
    return value


def _validate_target(target: SEC13FMaterializationTarget) -> None:
    if not target.accession_number:
        raise SECAcquisitionError("accession_number is required")
    if not target.filer_cik.isdigit():
        raise SECAcquisitionError("filer_cik must contain digits only")
    if target.filing_date < target.period_of_report:
        raise SECAcquisitionError("filing_date cannot precede period_of_report")
    if target.value_scale <= 0:
        raise SECAcquisitionError("value_scale must be positive")
    if target.canonicality not in {"CANONICAL", "NONCANONICAL"}:
        raise SECAcquisitionError("canonicality must be CANONICAL or NONCANONICAL")

    primary = urlparse(target.primary_document_url)
    table = urlparse(target.information_table_url)
    for parsed in (primary, table):
        if parsed.scheme != "https" or parsed.hostname not in {"www.sec.gov", "sec.gov"}:
            raise SECAcquisitionError("13F materialization URLs must use SEC HTTPS archives")
        if not parsed.path.startswith("/Archives/edgar/data/"):
            raise SECAcquisitionError("13F materialization URLs must use SEC EDGAR archive paths")
    if primary.path.rsplit("/", 1)[0] != table.path.rsplit("/", 1)[0]:
        raise SECAcquisitionError(
            "primary document and information table must share one filing directory"
        )

    if target.expected_primary_size is not None and target.expected_primary_size <= 0:
        raise SECAcquisitionError("expected_primary_size must be positive")
    if (
        target.expected_information_table_size is not None
        and target.expected_information_table_size <= 0
    ):
        raise SECAcquisitionError("expected_information_table_size must be positive")
    if target.canonicality == "CANONICAL" and (
        target.expected_primary_size is None or target.expected_information_table_size is None
    ):
        raise SECAcquisitionError(
            "CANONICAL materialization requires authoritative expected sizes for both SEC XML files"
        )


def _parse_primary_summary(primary_bytes: bytes) -> tuple[int, Decimal]:
    try:
        root = ET.fromstring(primary_bytes)
    except ET.ParseError as exc:
        raise SECAcquisitionError("invalid SEC 13F primary-document XML") from exc
    entry_total = _positive_int(_find_text(root, "tableEntryTotal"), "tableEntryTotal")
    value_total = _nonnegative_decimal(_find_text(root, "tableValueTotal"), "tableValueTotal")
    return entry_total, value_total


def _sum_reported_values(records: tuple[dict[str, object], ...]) -> Decimal:
    """Reconcile from preserved SEC value strings so floats never affect certification arithmetic."""
    total = Decimal(0)
    for index, record in enumerate(records, start=1):
        extra = record.get("extra")
        if not isinstance(extra, Mapping):
            raise SECAcquisitionError(f"13F row {index} has no preserved raw value metadata")
        raw_value = extra.get("raw_value")
        raw_scale = extra.get("value_scale")
        if raw_value in (None, "") or raw_scale is None:
            raise SECAcquisitionError(f"13F row {index} has incomplete raw value metadata")
        try:
            value = Decimal(str(raw_value))
            scale = Decimal(str(raw_scale))
        except InvalidOperation as exc:
            raise SECAcquisitionError(f"13F row {index} has invalid raw value metadata") from exc
        if value < 0 or scale <= 0:
            raise SECAcquisitionError(f"13F row {index} has invalid raw value or scale")
        total += value * scale
    return total


def materialize_sec_13f(
    client: SECFairAccessClient,
    target: SEC13FMaterializationTarget,
    destination_dir: Path,
) -> SEC13FMaterializationResult:
    """Freeze both SEC XML files and certify row/value reconciliation without aggregation."""
    _validate_target(target)
    destination_dir = Path(destination_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)

    primary_name = Path(urlparse(target.primary_document_url).path).name
    information_name = Path(urlparse(target.information_table_url).path).name
    primary_resource = client.freeze(
        target.primary_document_url,
        destination_dir / primary_name,
        expected_size=target.expected_primary_size,
    )
    information_resource = client.freeze(
        target.information_table_url,
        destination_dir / information_name,
        expected_size=target.expected_information_table_size,
    )

    primary_bytes = primary_resource.path.read_bytes()
    information_bytes = information_resource.path.read_bytes()
    declared_entry_total, declared_value_total = _parse_primary_summary(primary_bytes)

    metadata = SEC13FFilingMetadata(
        accession_number=target.accession_number,
        filer_cik=target.filer_cik,
        filing_date=target.filing_date,
        period_of_report=target.period_of_report,
        source_url=target.information_table_url,
        retrieval_utc=information_resource.receipt.retrieval_utc,
        value_scale=target.value_scale,
        canonicality=target.canonicality,
    )
    adapter = FrozenSEC13FAdapter(information_bytes, metadata)
    records = tuple(dict(record) for record in adapter.iter_records())
    parsed_entry_total = len(records)
    parsed_value_total = _sum_reported_values(records)

    if parsed_entry_total != declared_entry_total:
        raise SECAcquisitionError(
            "13F table-entry reconciliation failed: "
            f"primary={declared_entry_total}, parsed={parsed_entry_total}"
        )
    if parsed_value_total != declared_value_total:
        raise SECAcquisitionError(
            "13F table-value reconciliation failed: "
            f"primary={declared_value_total}, parsed={parsed_value_total}"
        )

    primary_sha256 = hashlib.sha256(primary_bytes).hexdigest()
    information_sha256 = hashlib.sha256(information_bytes).hexdigest()
    manifest = dict(adapter.source_manifest())
    manifest["primary_document_url"] = target.primary_document_url
    manifest["primary_document_sha256"] = primary_sha256
    manifest["primary_document_size"] = len(primary_bytes)
    manifest["declared_table_entry_total"] = declared_entry_total
    manifest["declared_table_value_total"] = str(declared_value_total)
    manifest["parsed_table_value_total"] = str(parsed_value_total)
    manifest["materialization_certification"] = (
        "PASS" if target.canonicality == "CANONICAL" else "PROVISIONAL"
    )

    return SEC13FMaterializationResult(
        target=target,
        primary_resource=primary_resource,
        information_table_resource=information_resource,
        primary_sha256=primary_sha256,
        information_table_sha256=information_sha256,
        declared_table_entry_total=declared_entry_total,
        parsed_table_entry_total=parsed_entry_total,
        declared_table_value_total=declared_value_total,
        parsed_table_value_total=parsed_value_total,
        source_manifest=manifest,
        certification_status="PASS" if target.canonicality == "CANONICAL" else "PROVISIONAL",
    )
