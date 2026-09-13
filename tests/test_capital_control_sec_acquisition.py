from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

import pytest
import requests

from moneysweep.capital_control import (
    SECAcquisitionError,
    SECFairAccessClient,
    SECRequestPolicy,
    SECTransport,
    SECTransportResponse,
    SECUserAgent,
)


@dataclass
class _Response:
    status_code: int
    content: bytes
    headers: Mapping[str, str]
    url: str


class _Transport:
    def __init__(self, responses: list[_Response | BaseException]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, str], float]] = []

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
    ) -> _Response:
        self.calls.append((url, dict(headers), timeout))
        if not self.responses:
            raise AssertionError("unexpected transport call")
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class _Clock:
    def __init__(self) -> None:
        self.value = 100.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += seconds


def _now() -> datetime:
    return datetime(2026, 8, 15, 11, 15, tzinfo=timezone.utc)


def _response(
    content: bytes = b"<informationTable/>",
    *,
    status: int = 200,
    headers: Mapping[str, str] | None = None,
    url: str = "https://www.sec.gov/Archives/example.xml",
) -> _Response:
    merged = {
        "Content-Type": "text/xml; charset=UTF-8",
        "Content-Length": str(len(content)),
    }
    if headers:
        merged.update(headers)
    return _Response(
        status_code=status,
        content=content,
        headers=merged,
        url=url,
    )


def _client(
    transport: _Transport,
    *,
    policy: SECRequestPolicy | None = None,
    clock: _Clock | None = None,
    now_utc=_now,
) -> SECFairAccessClient:
    clock = clock or _Clock()
    return SECFairAccessClient(
        SECUserAgent("MoneySweepPR/0.2", "research@example.org"),
        policy=policy,
        transport=transport,
        sleeper=clock.sleep,
        monotonic=clock.monotonic,
        now_utc=now_utc,
    )


def test_policy_never_allows_more_than_sec_fair_access_limit() -> None:
    SECRequestPolicy(max_requests_per_second=10).validate()
    with pytest.raises(SECAcquisitionError, match="fair-access"):
        SECRequestPolicy(max_requests_per_second=10.01).validate()


def test_protocol_placeholders_fail_explicitly() -> None:
    for name in ("status_code", "headers", "content", "url"):
        descriptor = vars(SECTransportResponse)[name]
        with pytest.raises(NotImplementedError):
            descriptor.fget(object())
    with pytest.raises(NotImplementedError):
        SECTransport.get(object(), "https://www.sec.gov/example", headers={}, timeout=1.0)


def test_user_agent_requires_declared_application_and_contact() -> None:
    assert (
        SECUserAgent("MoneySweepPR/0.2", "research@example.org").header_value()
        == "MoneySweepPR/0.2 research@example.org"
    )
    with pytest.raises(SECAcquisitionError, match="application and contact"):
        SECUserAgent("MoneySweepPR/0.2", " ").header_value()
    with pytest.raises(SECAcquisitionError, match="line breaks"):
        SECUserAgent("MoneySweepPR/0.2\nInjected", "research@example.org").header_value()


def test_fetch_declares_user_agent_and_preserves_provenance() -> None:
    content = b"authoritative-sec-bytes"
    transport = _Transport([_response(content)])
    client = _client(transport)

    data, receipt = client.fetch_bytes(
        "https://www.sec.gov/Archives/edgar/data/1/example.xml",
        expected_size=len(content),
        expected_sha256=hashlib.sha256(content).hexdigest(),
    )

    assert data == content
    assert receipt.byte_size == len(content)
    assert receipt.sha256 == hashlib.sha256(content).hexdigest()
    assert receipt.content_type == "text/xml"
    assert receipt.attempts == 1
    assert receipt.retrieval_utc == _now()
    assert transport.calls[0][1]["User-Agent"] == "MoneySweepPR/0.2 research@example.org"
    assert transport.calls[0][2] == 30.0


def test_non_sec_host_and_non_https_fail_before_transport() -> None:
    transport = _Transport([])
    client = _client(transport)
    with pytest.raises(SECAcquisitionError, match="non-SEC host"):
        client.fetch_bytes("https://example.com/file.xml")
    with pytest.raises(SECAcquisitionError, match="HTTPS"):
        client.fetch_bytes("http://www.sec.gov/file.xml")
    assert transport.calls == []


def test_successful_redirect_to_non_sec_host_is_rejected() -> None:
    client = _client(
        _Transport(
            [
                _response(
                    b"unexpected",
                    url="https://cdn.example.com/file.xml",
                )
            ]
        )
    )
    with pytest.raises(SECAcquisitionError, match="non-SEC host"):
        client.fetch_bytes("https://www.sec.gov/Archives/file.xml")


def test_retry_after_is_case_insensitive_and_honored_for_429() -> None:
    clock = _Clock()
    transport = _Transport(
        [
            _response(b"busy", status=429, headers={"retry-after": "2"}),
            _response(b"ok"),
        ]
    )
    client = _client(transport, clock=clock)

    data, receipt = client.fetch_bytes("https://www.sec.gov/Archives/file.xml")

    assert data == b"ok"
    assert receipt.attempts == 2
    assert any(seconds == 2.0 for seconds in clock.sleeps)
    assert len(transport.calls) == 2


def test_http_date_retry_after_is_supported() -> None:
    clock = _Clock()
    retry_at = "Sat, 15 Aug 2026 11:15:03 GMT"
    transport = _Transport(
        [
            _response(b"busy", status=503, headers={"Retry-After": retry_at}),
            _response(b"ok"),
        ]
    )
    client = _client(transport, clock=clock)

    data, receipt = client.fetch_bytes("https://www.sec.gov/Archives/file.xml")

    assert data == b"ok"
    assert receipt.attempts == 2
    assert 3.0 in clock.sleeps


def test_transport_failure_is_retried_then_succeeds() -> None:
    clock = _Clock()
    transport = _Transport(
        [
            requests.Timeout("temporary timeout"),
            _response(b"ok"),
        ]
    )
    client = _client(transport, clock=clock)

    data, receipt = client.fetch_bytes("https://www.sec.gov/Archives/file.xml")

    assert data == b"ok"
    assert receipt.attempts == 2
    assert len(transport.calls) == 2
    assert 1.0 in clock.sleeps


def test_non_retryable_http_failure_is_not_retried() -> None:
    transport = _Transport([_response(b"not found", status=404)])
    client = _client(transport)
    with pytest.raises(SECAcquisitionError, match="HTTP 404"):
        client.fetch_bytes("https://www.sec.gov/Archives/missing.xml")
    assert len(transport.calls) == 1


def test_exhausted_retryable_failures_fail_closed() -> None:
    policy = SECRequestPolicy(max_attempts=2, base_backoff_seconds=0)
    transport = _Transport(
        [
            _response(b"blocked", status=403),
            _response(b"blocked", status=403),
        ]
    )
    client = _client(transport, policy=policy)
    with pytest.raises(SECAcquisitionError, match="exhausted 2 attempts"):
        client.fetch_bytes("https://www.sec.gov/Archives/file.xml")
    assert len(transport.calls) == 2


def test_exhausted_transport_failures_preserve_failure_boundary() -> None:
    policy = SECRequestPolicy(max_attempts=2, base_backoff_seconds=0)
    transport = _Transport(
        [
            requests.Timeout("first"),
            requests.Timeout("second"),
        ]
    )
    client = _client(transport, policy=policy)
    with pytest.raises(SECAcquisitionError, match="transport retries"):
        client.fetch_bytes("https://www.sec.gov/Archives/file.xml")
    assert len(transport.calls) == 2


def test_content_type_size_and_hash_mismatch_fail_closed() -> None:
    with pytest.raises(SECAcquisitionError, match="content type"):
        _client(
            _Transport([_response(b"html", headers={"Content-Type": "text/html"})])
        ).fetch_bytes("https://www.sec.gov/Archives/file.xml")

    with pytest.raises(SECAcquisitionError, match="byte-size mismatch"):
        _client(_Transport([_response(b"abc")])).fetch_bytes(
            "https://www.sec.gov/Archives/file.xml", expected_size=4
        )

    with pytest.raises(SECAcquisitionError, match="SHA-256 mismatch"):
        _client(_Transport([_response(b"abc")])).fetch_bytes(
            "https://www.sec.gov/Archives/file.xml",
            expected_sha256="0" * 64,
        )


def test_non_utc_retrieval_clock_fails_closed() -> None:
    def non_utc() -> datetime:
        return datetime(2026, 8, 15, 12, 15, tzinfo=timezone(timedelta(hours=1)))

    client = _client(_Transport([_response(b"ok")]), now_utc=non_utc)
    with pytest.raises(SECAcquisitionError, match="timezone-aware UTC"):
        client.fetch_bytes("https://www.sec.gov/Archives/file.xml")


def test_freeze_is_atomic_and_idempotent_for_matching_bytes(tmp_path: Path) -> None:
    content = b"complete-sec-resource"
    destination = tmp_path / "source.xml"
    transport = _Transport([_response(content), _response(content)])
    client = _client(transport)

    first = client.freeze("https://www.sec.gov/Archives/source.xml", destination)
    second = client.freeze("https://www.sec.gov/Archives/source.xml", destination)

    assert first.write_status == "WRITTEN"
    assert second.write_status == "EXISTING_MATCH"
    assert destination.read_bytes() == content
    assert not list(tmp_path.glob("*.part"))
    assert not list(tmp_path.glob(".*.part"))


def test_freeze_refuses_silent_overwrite(tmp_path: Path) -> None:
    destination = tmp_path / "source.xml"
    destination.write_bytes(b"old-bytes")
    client = _client(_Transport([_response(b"new-bytes")]))

    with pytest.raises(SECAcquisitionError, match="refusing overwrite"):
        client.freeze("https://www.sec.gov/Archives/source.xml", destination)

    assert destination.read_bytes() == b"old-bytes"


def test_validation_failure_does_not_create_destination(tmp_path: Path) -> None:
    destination = tmp_path / "source.xml"
    client = _client(_Transport([_response(b"abc")]))

    with pytest.raises(SECAcquisitionError, match="byte-size mismatch"):
        client.freeze(
            "https://www.sec.gov/Archives/source.xml",
            destination,
            expected_size=999,
        )

    assert not destination.exists()
