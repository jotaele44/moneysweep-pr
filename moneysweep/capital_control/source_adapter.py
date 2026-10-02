from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

import requests


class SourceAdapter(Protocol):
    """Adapter contract: acquisition is source-specific; canonicalization is not."""

    def iter_records(self) -> Iterable[Mapping[str, Any]]:
        raise NotImplementedError

    def source_manifest(self) -> Mapping[str, Any]:
        raise NotImplementedError


def stable_observation_fingerprint(payload: Mapping[str, Any]) -> str:
    """Hash only identity-defining observation fields using canonical JSON serialization."""
    canonical = {
        key: payload.get(key)
        for key in (
            "holder_id",
            "issuer_id",
            "security_id",
            "security_class_raw",
            "position_class",
            "as_of_date",
            "report_date",
            "source_id",
            "source_record_id",
        )
    }
    encoded = json.dumps(
        canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


_ALLOWED_SEC_HOSTS = frozenset({"sec.gov", "www.sec.gov", "data.sec.gov"})
_RETRYABLE_STATUS_CODES = frozenset({403, 429, 500, 502, 503, 504})


class _SECAcquisitionError(RuntimeError):
    """Fail-closed acquisition error for authoritative SEC resources."""


@dataclass(frozen=True)
class _SECUserAgent:
    application: str
    contact: str

    def header_value(self) -> str:
        application = self.application.strip()
        contact = self.contact.strip()
        if not application or not contact:
            raise _SECAcquisitionError("SEC user agent requires application and contact")
        if any(char in application + contact for char in "\r\n"):
            raise _SECAcquisitionError("SEC user agent cannot contain line breaks")
        return f"{application} {contact}"


@dataclass(frozen=True)
class _SECRequestPolicy:
    max_requests_per_second: float = 5.0
    timeout_seconds: float = 30.0
    max_attempts: int = 4
    base_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 30.0
    allowed_content_types: tuple[str, ...] = (
        "text/xml",
        "application/xml",
        "text/plain",
        "application/json",
        "application/octet-stream",
    )

    def validate(self) -> None:
        if not 0 < self.max_requests_per_second <= 10:
            raise _SECAcquisitionError(
                "max_requests_per_second must be > 0 and <= SEC fair-access limit"
            )
        if self.timeout_seconds <= 0:
            raise _SECAcquisitionError("timeout_seconds must be positive")
        if self.max_attempts < 1:
            raise _SECAcquisitionError("max_attempts must be >= 1")
        if self.base_backoff_seconds < 0 or self.max_backoff_seconds < 0:
            raise _SECAcquisitionError("backoff values must be nonnegative")
        if self.base_backoff_seconds > self.max_backoff_seconds:
            raise _SECAcquisitionError("base_backoff_seconds exceeds max_backoff_seconds")
        if not self.allowed_content_types:
            raise _SECAcquisitionError("allowed_content_types cannot be empty")


class _SECTransportResponse(Protocol):
    @property
    def status_code(self) -> int:
        raise NotImplementedError

    @property
    def headers(self) -> Mapping[str, str]:
        raise NotImplementedError

    @property
    def content(self) -> bytes:
        raise NotImplementedError

    @property
    def url(self) -> str:
        raise NotImplementedError


class _SECTransport(Protocol):
    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
    ) -> _SECTransportResponse:
        raise NotImplementedError


class _RequestsSECTransport:
    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
    ) -> _SECTransportResponse:
        return self._session.get(url, headers=dict(headers), timeout=timeout)


@dataclass(frozen=True)
class _SECFetchReceipt:
    request_url: str
    response_url: str
    status_code: int
    retrieval_utc: datetime
    attempts: int
    content_type: str | None
    content_length_header: str | None
    etag: str | None
    last_modified: str | None
    byte_size: int
    sha256: str


@dataclass(frozen=True)
class _SECFrozenResource:
    receipt: _SECFetchReceipt
    path: Path
    write_status: str


def _header_value(headers: Mapping[str, str], name: str) -> str | None:
    wanted = name.casefold()
    for key, value in headers.items():
        if key.casefold() == wanted:
            return value
    return None


class _SECFairAccessClient:
    """Rate-limited, provenance-preserving SEC fetcher with fail-closed freezing."""

    def __init__(
        self,
        user_agent: _SECUserAgent,
        *,
        policy: _SECRequestPolicy | None = None,
        transport: _SECTransport | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        now_utc: Callable[[], datetime] | None = None,
    ) -> None:
        self.user_agent = user_agent
        self.policy = policy or _SECRequestPolicy()
        self.policy.validate()
        self.user_agent.header_value()
        self._transport: _SECTransport = transport or _RequestsSECTransport()
        self._sleep = sleeper
        self._monotonic = monotonic
        self._now_utc = now_utc or (lambda: datetime.now(timezone.utc))
        self._last_request_monotonic: float | None = None

    @staticmethod
    def _validate_url(url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https":
            raise _SECAcquisitionError("SEC acquisition requires HTTPS")
        hostname = (parsed.hostname or "").lower()
        if hostname not in _ALLOWED_SEC_HOSTS:
            raise _SECAcquisitionError(f"non-SEC host rejected: {hostname or '<empty>'}")
        if not parsed.path:
            raise _SECAcquisitionError("SEC URL must include a path")

    def _rate_limit(self) -> None:
        interval = 1.0 / self.policy.max_requests_per_second
        now = self._monotonic()
        if self._last_request_monotonic is not None:
            remaining = interval - (now - self._last_request_monotonic)
            if remaining > 0:
                self._sleep(remaining)
                now = self._monotonic()
        self._last_request_monotonic = now

    @staticmethod
    def _retry_after_seconds(value: str | None, now: datetime) -> float | None:
        if not value:
            return None
        stripped = value.strip()
        try:
            return max(0.0, float(stripped))
        except ValueError:
            pass
        try:
            retry_at = parsedate_to_datetime(stripped)
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        return max(
            0.0,
            (retry_at.astimezone(timezone.utc) - now).total_seconds(),
        )

    def _backoff_seconds(
        self,
        attempt: int,
        headers: Mapping[str, str],
        now: datetime,
    ) -> float:
        retry_after = self._retry_after_seconds(_header_value(headers, "Retry-After"), now)
        if retry_after is not None:
            return min(retry_after, self.policy.max_backoff_seconds)
        exponential = self.policy.base_backoff_seconds * (2 ** max(0, attempt - 1))
        return min(exponential, self.policy.max_backoff_seconds)

    def _retrieval_utc(self) -> datetime:
        value = self._now_utc()
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise _SECAcquisitionError("now_utc must return timezone-aware UTC datetime")
        return value

    def fetch_bytes(
        self,
        url: str,
        *,
        expected_size: int | None = None,
        expected_sha256: str | None = None,
    ) -> tuple[bytes, _SECFetchReceipt]:
        self._validate_url(url)
        if expected_size is not None and expected_size < 0:
            raise _SECAcquisitionError("expected_size must be nonnegative")
        if expected_sha256 is not None and (
            len(expected_sha256) != 64
            or any(char not in "0123456789abcdef" for char in expected_sha256)
        ):
            raise _SECAcquisitionError("expected_sha256 must be 64 lowercase hex characters")

        headers = {
            "User-Agent": self.user_agent.header_value(),
            "Accept-Encoding": "gzip, deflate",
            "Accept": "*/*",
        }
        last_status: int | None = None
        last_transport_error: BaseException | None = None

        for attempt in range(1, self.policy.max_attempts + 1):
            self._rate_limit()
            try:
                response = self._transport.get(
                    url,
                    headers=headers,
                    timeout=self.policy.timeout_seconds,
                )
            except (requests.RequestException, TimeoutError, OSError) as exc:
                last_transport_error = exc
                if attempt == self.policy.max_attempts:
                    break
                delay = min(
                    self.policy.base_backoff_seconds * (2 ** max(0, attempt - 1)),
                    self.policy.max_backoff_seconds,
                )
                if delay > 0:
                    self._sleep(delay)
                continue

            retrieval_utc = self._retrieval_utc()
            last_status = response.status_code

            if 200 <= response.status_code < 300:
                self._validate_url(response.url)
                content = bytes(response.content)
                if not content:
                    raise _SECAcquisitionError("SEC response body is empty")

                raw_content_type = _header_value(response.headers, "Content-Type")
                content_type = (
                    raw_content_type.split(";", 1)[0].strip().lower() if raw_content_type else None
                )
                allowed = {item.lower() for item in self.policy.allowed_content_types}
                if content_type is not None and content_type not in allowed:
                    raise _SECAcquisitionError(f"unexpected SEC content type: {content_type}")

                digest = hashlib.sha256(content).hexdigest()
                if expected_size is not None and len(content) != expected_size:
                    raise _SECAcquisitionError(
                        f"SEC byte-size mismatch: expected {expected_size}, got {len(content)}"
                    )
                if expected_sha256 is not None and digest != expected_sha256:
                    raise _SECAcquisitionError("SEC SHA-256 mismatch")

                receipt = _SECFetchReceipt(
                    request_url=url,
                    response_url=response.url,
                    status_code=response.status_code,
                    retrieval_utc=retrieval_utc,
                    attempts=attempt,
                    content_type=content_type,
                    content_length_header=_header_value(response.headers, "Content-Length"),
                    etag=_header_value(response.headers, "ETag"),
                    last_modified=_header_value(response.headers, "Last-Modified"),
                    byte_size=len(content),
                    sha256=digest,
                )
                return content, receipt

            if response.status_code not in _RETRYABLE_STATUS_CODES:
                raise _SECAcquisitionError(f"SEC request failed with HTTP {response.status_code}")
            if attempt == self.policy.max_attempts:
                break
            delay = self._backoff_seconds(attempt, response.headers, retrieval_utc)
            if delay > 0:
                self._sleep(delay)

        if last_transport_error is not None and last_status is None:
            raise _SECAcquisitionError(
                "SEC request exhausted transport retries without a response"
            ) from last_transport_error
        status: int | str = last_status if last_status is not None else "NO_RESPONSE"
        raise _SECAcquisitionError(
            f"SEC request exhausted {self.policy.max_attempts} attempts; last status={status}"
        )

    def freeze(
        self,
        url: str,
        destination: Path,
        *,
        expected_size: int | None = None,
        expected_sha256: str | None = None,
    ) -> _SECFrozenResource:
        content, receipt = self.fetch_bytes(
            url,
            expected_size=expected_size,
            expected_sha256=expected_sha256,
        )
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)

        if destination.exists():
            existing = destination.read_bytes()
            existing_sha = hashlib.sha256(existing).hexdigest()
            if existing_sha == receipt.sha256 and len(existing) == receipt.byte_size:
                return _SECFrozenResource(
                    receipt=receipt,
                    path=destination,
                    write_status="EXISTING_MATCH",
                )
            raise _SECAcquisitionError(
                "destination already exists with different bytes; refusing overwrite"
            )

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=destination.parent,
                prefix=f".{destination.name}.",
                suffix=".part",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, destination)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

        frozen = destination.read_bytes()
        if len(frozen) != receipt.byte_size:
            destination.unlink(missing_ok=True)
            raise _SECAcquisitionError("post-write byte-size verification failed")
        if hashlib.sha256(frozen).hexdigest() != receipt.sha256:
            destination.unlink(missing_ok=True)
            raise _SECAcquisitionError("post-write SHA-256 verification failed")

        return _SECFrozenResource(
            receipt=receipt,
            path=destination,
            write_status="WRITTEN",
        )


@dataclass(frozen=True)
class _CapitalSourceDefinition:
    source_key: str
    authority: str
    source_family: str
    form_types: frozenset[str]
    canonicality: str
    acquisition_mode: str
    official_locator: str
    technical_spec_locator: str
    denominator_rule: str
    update_cadence: str
    semantic_limit: str


_SEC_SOURCE_DEFINITIONS: tuple[_CapitalSourceDefinition, ...] = (
    _CapitalSourceDefinition(
        source_key="SEC_13F",
        authority="U.S. Securities and Exchange Commission",
        source_family="REGULATORY_HOLDINGS",
        form_types=frozenset({"13F-HR", "13F-HR/A", "13F-NT", "13F-NT/A"}),
        canonicality="CANONICAL",
        acquisition_mode="EDGAR_FILING_AND_QUARTERLY_BULK_DATASET",
        official_locator="https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets",
        technical_spec_locator="https://www.sec.gov/submit-filings/technical-specifications",
        denominator_rule=(
            "Enumerate authoritative EDGAR filings or SEC quarterly 13F bulk data; "
            "do not treat web search results as a denominator. Preserve amendments as separate filings."
        ),
        update_cadence="QUARTERLY_BULK_PLUS_LIVE_EDGAR",
        semantic_limit=(
            "13F reports institutional investment discretion over reportable securities; "
            "it is not automatic beneficial-ownership proof."
        ),
    ),
    _CapitalSourceDefinition(
        source_key="SEC_13D_G",
        authority="U.S. Securities and Exchange Commission",
        source_family="BENEFICIAL_OWNERSHIP",
        form_types=frozenset({"SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A"}),
        canonicality="CANONICAL",
        acquisition_mode="EDGAR_FILING",
        official_locator="https://www.sec.gov/edgar/search/",
        technical_spec_locator="https://www.sec.gov/submit-filings/technical-specifications",
        denominator_rule=(
            "Enumerate authoritative EDGAR submission records for the exact schedule types and scope; "
            "retain amendments and filing dates."
        ),
        update_cadence="LIVE_EDGAR",
        semantic_limit=(
            "Schedule 13D/G reports beneficial-ownership information under its filing rules; "
            "reported persons and group relationships remain distinct until explicitly bound."
        ),
    ),
    _CapitalSourceDefinition(
        source_key="SEC_FORMS_3_4_5",
        authority="U.S. Securities and Exchange Commission",
        source_family="INSIDER_FILING",
        form_types=frozenset({"3", "3/A", "4", "4/A", "5", "5/A"}),
        canonicality="CANONICAL",
        acquisition_mode="EDGAR_FILING",
        official_locator="https://www.sec.gov/edgar/search/",
        technical_spec_locator="https://www.sec.gov/submit-filings/technical-specifications",
        denominator_rule=(
            "Enumerate authoritative EDGAR ownership submissions for exact issuer/reporting-owner scope; "
            "retain derivative and non-derivative tables separately."
        ),
        update_cadence="LIVE_EDGAR",
        semantic_limit=(
            "Section 16 reporting-owner status and transaction reporting do not by themselves establish "
            "ultimate-parent or investor-family identity."
        ),
    ),
    _CapitalSourceDefinition(
        source_key="SEC_NPORT",
        authority="U.S. Securities and Exchange Commission",
        source_family="FUND_HOLDINGS",
        form_types=frozenset({"NPORT-P", "NPORT-P/A", "NPORT-NP", "NPORT-NP/A"}),
        canonicality="CANONICAL",
        acquisition_mode="EDGAR_FILING",
        official_locator="https://www.sec.gov/edgar/search/",
        technical_spec_locator="https://www.sec.gov/submit-filings/technical-specifications",
        denominator_rule=(
            "Enumerate authoritative EDGAR N-PORT submissions for the registered-fund scope; "
            "respect public/non-public filing treatment and amendments."
        ),
        update_cadence="MONTHLY_OR_AS_REQUIRED_BY_FORM_RULES",
        semantic_limit=(
            "N-PORT describes fund portfolio holdings; fund, adviser, sponsor, beneficial owner, and ultimate "
            "parent identities must remain separate."
        ),
    ),
)

_SOURCE_BY_KEY = {item.source_key: item for item in _SEC_SOURCE_DEFINITIONS}


def _source_definition(source_key: str) -> _CapitalSourceDefinition:
    try:
        return _SOURCE_BY_KEY[source_key]
    except KeyError as exc:
        raise ValueError(f"unknown capital source definition: {source_key}") from exc


def _source_for_form_type(form_type: str) -> _CapitalSourceDefinition:
    matches = [item for item in _SEC_SOURCE_DEFINITIONS if form_type in item.form_types]
    if len(matches) != 1:
        raise ValueError(f"form type must resolve to exactly one source definition: {form_type!r}")
    return matches[0]


def _assert_source_registry_invariants(items: Iterable[_CapitalSourceDefinition]) -> None:
    rows = tuple(items)
    keys = [row.source_key for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate source_key")
    claimed_forms: set[str] = set()
    for row in rows:
        if not row.form_types:
            raise ValueError(f"source definition has no form types: {row.source_key}")
        overlap = claimed_forms & set(row.form_types)
        if overlap:
            raise ValueError(f"form types mapped to multiple source definitions: {sorted(overlap)}")
        claimed_forms.update(row.form_types)
        if row.canonicality != "CANONICAL":
            raise ValueError("authoritative SEC registry entries must be canonical")
        if not row.official_locator.startswith("https://www.sec.gov/"):
            raise ValueError("SEC official locator must use sec.gov")
        if not row.technical_spec_locator.startswith("https://www.sec.gov/"):
            raise ValueError("SEC technical specification locator must use sec.gov")


_assert_source_registry_invariants(_SEC_SOURCE_DEFINITIONS)


@dataclass(frozen=True)
class _FilingIndexRecord:
    accession_number: str
    cik: str
    form_type: str
    filing_date: date
    report_date: date | None
    source_url: str


@dataclass(frozen=True)
class _DenominatorResult:
    source_key: str
    input_count: int
    retained: tuple[_FilingIndexRecord, ...]
    excluded: tuple[_FilingIndexRecord, ...]
    exclusion_counts: tuple[tuple[str, int], ...]

    @property
    def retained_count(self) -> int:
        return len(self.retained)

    @property
    def excluded_count(self) -> int:
        return len(self.excluded)


def _validate_filing_index_record(row: _FilingIndexRecord) -> None:
    if not row.accession_number or not row.cik or not row.form_type:
        raise ValueError("accession_number, cik, and form_type are required")
    if not row.source_url.startswith("https://www.sec.gov/"):
        raise ValueError("SEC filing index record must bind to sec.gov")
    if row.report_date is not None and row.filing_date < row.report_date:
        raise ValueError("filing_date cannot precede report_date")


def _build_filing_denominator(
    records: Iterable[_FilingIndexRecord],
    definition: _CapitalSourceDefinition,
) -> _DenominatorResult:
    """Classify a supplied authoritative index universe; discovery search is not a denominator."""
    rows = tuple(records)
    seen: set[str] = set()
    retained: list[_FilingIndexRecord] = []
    excluded: list[_FilingIndexRecord] = []
    reasons: Counter[str] = Counter()

    for row in rows:
        _validate_filing_index_record(row)
        if row.accession_number in seen:
            raise ValueError(f"duplicate accession_number: {row.accession_number}")
        seen.add(row.accession_number)
        if row.form_type in definition.form_types:
            retained.append(row)
        else:
            excluded.append(row)
            reasons["FORM_TYPE_OUT_OF_SCOPE"] += 1

    if len(rows) != len(retained) + len(excluded):
        raise AssertionError("denominator arithmetic does not close")

    def _sort_key(row: _FilingIndexRecord) -> tuple[date, str]:
        return row.filing_date, row.accession_number

    return _DenominatorResult(
        source_key=definition.source_key,
        input_count=len(rows),
        retained=tuple(sorted(retained, key=_sort_key)),
        excluded=tuple(sorted(excluded, key=_sort_key)),
        exclusion_counts=tuple(sorted(reasons.items())),
    )


@dataclass(frozen=True)
class _SEC13FFilingMetadata:
    accession_number: str
    filer_cik: str
    filing_date: date
    period_of_report: date
    source_url: str
    retrieval_utc: datetime
    value_scale: float
    is_amendment: bool = False
    canonicality: str = "CANONICAL"
    supersedes_by_source_record_id: Mapping[str, str] | None = None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children_by_local(element: ET.Element) -> dict[str, ET.Element]:
    return {_local_name(child.tag): child for child in list(element)}


def _text(element: ET.Element | None) -> str | None:
    if element is None or element.text is None:
        return None
    return element.text.strip()


def _descendant_text(element: ET.Element, *path: str) -> str | None:
    cursor = element
    for name in path:
        child = _children_by_local(cursor).get(name)
        if child is None:
            return None
        cursor = child
    return _text(cursor)


def _number(raw: str | None, field: str) -> float | None:
    if raw in (None, ""):
        return None
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"invalid numeric {field}: {raw!r}") from exc


def _validate_13f_metadata(metadata: _SEC13FFilingMetadata) -> None:
    if not metadata.accession_number:
        raise ValueError("accession_number is required")
    if not metadata.filer_cik.isdigit():
        raise ValueError("filer_cik must contain digits only")
    if metadata.filing_date < metadata.period_of_report:
        raise ValueError("filing_date cannot precede period_of_report")
    if not metadata.source_url.startswith("https://www.sec.gov/Archives/edgar/data/"):
        raise ValueError("13F source_url must be an SEC EDGAR archive URL")
    offset = metadata.retrieval_utc.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise ValueError("retrieval_utc must be timezone-aware UTC")
    if metadata.value_scale <= 0:
        raise ValueError("value_scale must be positive and explicit")
    if metadata.canonicality not in {"CANONICAL", "CORROBORATING", "NONCANONICAL"}:
        raise ValueError("unsupported 13F source canonicality")


class _FrozenSEC13FAdapter:
    """Parse frozen SEC Form 13F information-table XML without aggregating source rows."""

    def __init__(self, xml_bytes: bytes, metadata: _SEC13FFilingMetadata) -> None:
        _validate_13f_metadata(metadata)
        if not xml_bytes:
            raise ValueError("xml_bytes cannot be empty")
        self._xml_bytes = bytes(xml_bytes)
        self._metadata = metadata
        try:
            self._root = ET.fromstring(self._xml_bytes)
        except ET.ParseError as exc:
            raise ValueError("invalid SEC 13F XML") from exc
        if _local_name(self._root.tag) != "informationTable":
            raise ValueError("expected SEC 13F informationTable root")

    @property
    def source_id(self) -> str:
        accession = "".join(ch for ch in self._metadata.accession_number if ch.isalnum())
        return f"SRC_CAP_SEC_13F_{accession}"

    def _info_tables(self) -> tuple[ET.Element, ...]:
        return tuple(child for child in list(self._root) if _local_name(child.tag) == "infoTable")

    def source_manifest(self) -> Mapping[str, Any]:
        rows = self._info_tables()
        digest = hashlib.sha256(self._xml_bytes).hexdigest()
        return {
            "source_id": self.source_id,
            "source_family": "REGULATORY_HOLDINGS",
            "source_authority": "U.S. Securities and Exchange Commission",
            "retrieval_utc": self._metadata.retrieval_utc,
            "source_url_or_locator": self._metadata.source_url,
            "byte_status": "FROZEN",
            "source_as_of_date": self._metadata.period_of_report,
            "refresh_date": self._metadata.filing_date,
            "query_identity": f"EDGAR accession {self._metadata.accession_number}",
            "page_or_offset": "INFORMATION_TABLE_XML",
            "raw_bytes_sha256": digest,
            "raw_bytes_size": len(self._xml_bytes),
            "schema_fingerprint": (
                f"SEC_FORM_13F_INFORMATION_TABLE_XML:value_scale={self._metadata.value_scale:g}"
            ),
            "record_count": len(rows),
            "canonicality": self._metadata.canonicality,
            "notes": (
                "Frozen 13F information-table XML; rows are not aggregated. "
                "CANONICAL is valid only for complete as-filed SEC bytes."
            ),
        }

    def iter_records(self) -> Iterable[Mapping[str, Any]]:
        digest = hashlib.sha256(self._xml_bytes).hexdigest()
        for index, row in enumerate(self._info_tables(), start=1):
            children = _children_by_local(row)
            issuer_name = _text(children.get("nameOfIssuer"))
            security_class = _text(children.get("titleOfClass"))
            cusip = _text(children.get("cusip"))
            figi = _text(children.get("figi"))
            value_raw = _text(children.get("value"))
            shares_raw = _descendant_text(row, "shrsOrPrnAmt", "sshPrnamt")
            shares_type = _descendant_text(row, "shrsOrPrnAmt", "sshPrnamtType")
            investment_discretion = _text(children.get("investmentDiscretion"))
            other_manager = _text(children.get("otherManager"))
            put_call = _text(children.get("putCall"))
            sole = _descendant_text(row, "votingAuthority", "Sole")
            shared = _descendant_text(row, "votingAuthority", "Shared")
            none_value = _descendant_text(row, "votingAuthority", "None")

            if not issuer_name:
                raise ValueError(f"13F row {index} missing nameOfIssuer")
            if not security_class and not cusip:
                raise ValueError(f"13F row {index} missing both titleOfClass and cusip")
            if not investment_discretion:
                raise ValueError(f"13F row {index} missing investmentDiscretion")

            source_record_id = f"{self._metadata.accession_number}:INFOTABLE:{index}"
            supersedes = None
            if self._metadata.supersedes_by_source_record_id:
                supersedes = self._metadata.supersedes_by_source_record_id.get(source_record_id)

            security_id = f"CUSIP:{cusip}" if cusip else None
            issuer_id = (
                f"SEC_13F_SECURITY:{cusip}" if cusip else f"SEC_13F_UNRESOLVED_ISSUER:{index}"
            )
            observation_hash = hashlib.sha256(source_record_id.encode("utf-8")).hexdigest()[:20]
            shares = _number(shares_raw, "sshPrnamt")
            market_value = _number(value_raw, "value")
            if market_value is not None:
                market_value *= self._metadata.value_scale

            yield {
                "observation_id": f"HOLD_SEC13F_{observation_hash}",
                "holder_id": (f"INV_SEC_CIK_{self._metadata.filer_cik.zfill(10)}"),
                "issuer_id": issuer_id,
                "position_class": "INVESTMENT_DISCRETION",
                "as_of_date": self._metadata.period_of_report,
                "report_date": self._metadata.filing_date,
                "source_id": self.source_id,
                "source_record_id": source_record_id,
                "identity_status": "PASS",
                "security_id": security_id,
                "security_class_raw": security_class,
                "direct_or_indirect": "UNKNOWN",
                "shares": shares if shares_type == "SH" else None,
                "principal_amount": shares if shares_type == "PRN" else None,
                "market_value": market_value,
                "currency": "USD",
                "sole_voting_power": _number(sole, "Sole"),
                "shared_voting_power": _number(shared, "Shared"),
                "beneficial_owner_status": "UNKNOWN",
                "investment_adviser_status": "UNKNOWN",
                "control_status": "UNKNOWN",
                "amendment_status": "AMENDED" if supersedes else "ORIGINAL",
                "supersedes_observation_id": supersedes,
                "source_document_sha256": digest,
                "notes": ("13F investment-discretion observation; not beneficial-ownership proof."),
                "extra": {
                    "raw_name_of_issuer": issuer_name,
                    "raw_title_of_class": security_class,
                    "raw_cusip": cusip,
                    "raw_figi": figi,
                    "raw_value": value_raw,
                    "value_scale": self._metadata.value_scale,
                    "raw_shares_or_principal_amount": shares_raw,
                    "raw_shares_or_principal_type": shares_type,
                    "raw_investment_discretion": investment_discretion,
                    "raw_other_manager": other_manager,
                    "raw_put_call": put_call,
                    "raw_voting_none": none_value,
                    "source_is_amendment": self._metadata.is_amendment,
                },
            }


SECAcquisitionError = _SECAcquisitionError
SECUserAgent = _SECUserAgent
SECRequestPolicy = _SECRequestPolicy
SECTransportResponse = _SECTransportResponse
SECTransport = _SECTransport
RequestsSECTransport = _RequestsSECTransport
SECFetchReceipt = _SECFetchReceipt
SECFrozenResource = _SECFrozenResource
SECFairAccessClient = _SECFairAccessClient
CapitalSourceDefinition = _CapitalSourceDefinition
SEC_SOURCE_DEFINITIONS = _SEC_SOURCE_DEFINITIONS
source_definition = _source_definition
source_for_form_type = _source_for_form_type
assert_source_registry_invariants = _assert_source_registry_invariants
FilingIndexRecord = _FilingIndexRecord
DenominatorResult = _DenominatorResult
build_filing_denominator = _build_filing_denominator
SEC13FFilingMetadata = _SEC13FFilingMetadata
FrozenSEC13FAdapter = _FrozenSEC13FAdapter
