from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from moneysweep.capital_control.ingestion import ingest
from moneysweep.capital_control.source_adapter import FrozenSEC13FAdapter, SEC13FFilingMetadata


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "capital_control"
    / "sec_13f_0001193125_26_226661_excerpt.xml"
)


def _metadata(value_scale: float = 1.0) -> SEC13FFilingMetadata:
    return SEC13FFilingMetadata(
        accession_number="0001193125-26-226661",
        filer_cik="0001067983",
        filing_date=date(2026, 5, 15),
        period_of_report=date(2026, 3, 31),
        source_url=("https://www.sec.gov/Archives/edgar/data/1067983/000119312526226661/53405.xml"),
        retrieval_utc=datetime(2026, 8, 15, 10, 49, tzinfo=timezone.utc),
        value_scale=value_scale,
        canonicality="NONCANONICAL",
    )


def test_real_world_sec_excerpt_materializes_without_aggregation() -> None:
    adapter = FrozenSEC13FAdapter(FIXTURE.read_bytes(), _metadata())
    result = ingest(adapter)
    assert result.input_count == 2
    assert result.retained_count == 2
    first, second = result.observations
    assert first.holder_id == "INV_SEC_CIK_0001067983"
    assert first.issuer_id == "SEC_13F_SECURITY:02005N100"
    assert first.security_id == "CUSIP:02005N100"
    assert first.security_class_raw == "COM"
    assert first.position_class == "INVESTMENT_DISCRETION"
    assert first.beneficial_owner_status == "UNKNOWN"
    assert first.market_value == 498_992_850
    assert first.shares == 12_719_675
    assert first.sole_voting_power == 12_719_675
    assert first.extra["raw_other_manager"] == "4"
    assert second.extra["raw_other_manager"] == "2,4,11"
    assert result.manifest.canonicality == "NONCANONICAL"


def test_value_scale_is_explicit_and_applied() -> None:
    adapter = FrozenSEC13FAdapter(FIXTURE.read_bytes(), _metadata(value_scale=1000.0))
    first = next(iter(adapter.iter_records()))
    assert first["market_value"] == 498_992_850_000
    assert first["extra"]["value_scale"] == 1000.0


def test_invalid_or_implicit_scale_fails_closed() -> None:
    with pytest.raises(ValueError, match="value_scale"):
        FrozenSEC13FAdapter(FIXTURE.read_bytes(), _metadata(value_scale=0.0))


def test_non_13f_root_fails_closed() -> None:
    with pytest.raises(ValueError, match="informationTable"):
        FrozenSEC13FAdapter(b"<root/>", _metadata())
