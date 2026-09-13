from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Mapping

import pytest

from moneysweep.capital_control import (
    SEC13FMaterializationTarget,
    SECAcquisitionError,
    SECFairAccessClient,
    SECUserAgent,
    materialize_sec_13f,
)


PRIMARY_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission>
  <formData>
    <summaryPage>
      <otherIncludedManagersCount>0</otherIncludedManagersCount>
      <tableEntryTotal>2</tableEntryTotal>
      <tableValueTotal>300</tableValueTotal>
    </summaryPage>
  </formData>
</edgarSubmission>
"""

INFORMATION_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<informationTable>
  <infoTable>
    <nameOfIssuer>Issuer One</nameOfIssuer>
    <titleOfClass>COM</titleOfClass>
    <cusip>000000001</cusip>
    <value>100</value>
    <shrsOrPrnAmt><sshPrnamt>10</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
    <investmentDiscretion>SOLE</investmentDiscretion>
    <votingAuthority><Sole>10</Sole><Shared>0</Shared><None>0</None></votingAuthority>
  </infoTable>
  <infoTable>
    <nameOfIssuer>Issuer Two</nameOfIssuer>
    <titleOfClass>COM</titleOfClass>
    <cusip>000000002</cusip>
    <value>200</value>
    <shrsOrPrnAmt><sshPrnamt>20</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
    <investmentDiscretion>SOLE</investmentDiscretion>
    <votingAuthority><Sole>20</Sole><Shared>0</Shared><None>0</None></votingAuthority>
  </infoTable>
</informationTable>
"""


@dataclass(frozen=True)
class _Response:
    status_code: int
    content: bytes
    headers: Mapping[str, str]
    url: str


class _Transport:
    def __init__(self, responses: list[_Response]) -> None:
        self.responses = list(responses)

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
    ) -> _Response:
        del headers, timeout
        if not self.responses:
            raise AssertionError("unexpected SEC transport call")
        response = self.responses.pop(0)
        assert response.url == url
        return response


def _response(url: str, content: bytes) -> _Response:
    return _Response(
        status_code=200,
        content=content,
        headers={"Content-Type": "text/xml", "Content-Length": str(len(content))},
        url=url,
    )


def _target(**overrides: object) -> SEC13FMaterializationTarget:
    values: dict[str, object] = {
        "accession_number": "0000000000-26-000001",
        "filer_cik": "123456",
        "filing_date": date(2026, 5, 15),
        "period_of_report": date(2026, 3, 31),
        "primary_document_url": (
            "https://www.sec.gov/Archives/edgar/data/123456/000000000026000001/primary_doc.xml"
        ),
        "information_table_url": (
            "https://www.sec.gov/Archives/edgar/data/123456/000000000026000001/table.xml"
        ),
        "value_scale": 1.0,
        "expected_primary_size": len(PRIMARY_XML),
        "expected_information_table_size": len(INFORMATION_XML),
        "canonicality": "CANONICAL",
    }
    values.update(overrides)
    return SEC13FMaterializationTarget(**values)  # type: ignore[arg-type]


def _client(
    target: SEC13FMaterializationTarget, info_bytes: bytes = INFORMATION_XML
) -> SECFairAccessClient:
    transport = _Transport(
        [
            _response(target.primary_document_url, PRIMARY_XML),
            _response(target.information_table_url, info_bytes),
        ]
    )
    return SECFairAccessClient(
        SECUserAgent("MoneySweepPR/0.2", "research@example.org"),
        transport=transport,
        sleeper=lambda seconds: None,
        monotonic=lambda: 100.0,
        now_utc=lambda: datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc),
    )


def test_complete_pair_reconciles_and_certifies(tmp_path: Path) -> None:
    target = _target()
    result = materialize_sec_13f(_client(target), target, tmp_path)

    assert result.certification_status == "PASS"
    assert result.declared_table_entry_total == 2
    assert result.parsed_table_entry_total == 2
    assert str(result.declared_table_value_total) == "300"
    assert str(result.parsed_table_value_total) == "300.0"
    assert result.primary_resource.path.read_bytes() == PRIMARY_XML
    assert result.information_table_resource.path.read_bytes() == INFORMATION_XML
    assert result.source_manifest["materialization_certification"] == "PASS"
    assert result.source_manifest["declared_table_entry_total"] == 2


def test_canonical_materialization_requires_authoritative_file_sizes(
    tmp_path: Path,
) -> None:
    target = _target(expected_primary_size=None)
    with pytest.raises(SECAcquisitionError, match="expected sizes"):
        materialize_sec_13f(_client(target), target, tmp_path)


def test_primary_and_information_table_must_share_filing_directory(
    tmp_path: Path,
) -> None:
    target = _target(
        information_table_url=("https://www.sec.gov/Archives/edgar/data/123456/DIFFERENT/table.xml")
    )
    with pytest.raises(SECAcquisitionError, match="share one filing directory"):
        materialize_sec_13f(_client(target), target, tmp_path)


def test_row_count_mismatch_fails_closed_after_preserving_frozen_bytes(
    tmp_path: Path,
) -> None:
    one_row = INFORMATION_XML.replace(
        b"  <infoTable>\n    <nameOfIssuer>Issuer Two</nameOfIssuer>",
        b"  <ignoredTable>\n    <nameOfIssuer>Issuer Two</nameOfIssuer>",
    ).replace(
        b"  </infoTable>\n</informationTable>",
        b"  </ignoredTable>\n</informationTable>",
    )
    target = _target(expected_information_table_size=len(one_row))

    with pytest.raises(SECAcquisitionError, match="table-entry reconciliation failed"):
        materialize_sec_13f(_client(target, one_row), target, tmp_path)

    assert (tmp_path / "primary_doc.xml").read_bytes() == PRIMARY_XML
    assert (tmp_path / "table.xml").read_bytes() == one_row


def test_value_total_mismatch_fails_closed(tmp_path: Path) -> None:
    wrong_value = INFORMATION_XML.replace(b"<value>200</value>", b"<value>201</value>")
    target = _target(expected_information_table_size=len(wrong_value))

    with pytest.raises(SECAcquisitionError, match="table-value reconciliation failed"):
        materialize_sec_13f(_client(target, wrong_value), target, tmp_path)
