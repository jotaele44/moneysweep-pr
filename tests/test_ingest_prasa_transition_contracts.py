from pathlib import Path

import pytest

import scripts.ingest_prasa_transition_contracts as transition_contracts


parse_prasa_transition_contracts = transition_contracts.parse_prasa_transition_contracts


def _source() -> Path:
    return Path(
        "/Users/jotaele/Documents/Financials/2024/ACT/transicion2024_archive/files/by_agency/163/"
        "Informe_de_Contratos_Vigentes/Contratos_Vigentes_al_24_de_septiembre_de_2024_Informe.pdf"
    )


def test_parse_prasa_transition_contracts_from_authoritative_pdf():
    source = _source()
    if not source.exists():
        pytest.skip("external PRASA transition PDF is not available in this workspace")

    frame, receipt = parse_prasa_transition_contracts(source)

    assert len(frame) >= 600
    assert frame["contract_id"].is_unique
    assert "2021-000162-G" in set(frame["contract_id"])
    row = frame.loc[frame["contract_id"] == "2021-000162-G"].iloc[0]
    assert row["vendor_name"] == "Black & Veatch Puerto Rico, PSC"
    assert row["contract_value"] == "$125,275,430.00"
    assert row["status"] == "vigente"
    assert receipt["classification"] == "FOUND_STRUCTURED_FROM_AUTHORITY_TRANSITION_PDF"
    assert receipt["rows_parsed"] == len(frame)
    assert receipt["duplicate_contract_ids"] == 0


def test_pdfplumber_fallback_preserves_authoritative_layout(monkeypatch):
    source = _source()
    if not source.exists():
        pytest.skip("external PRASA transition PDF is not available in this workspace")

    def missing_pdftotext(*args, **kwargs):
        raise FileNotFoundError("pdftotext")

    monkeypatch.setattr(transition_contracts.subprocess, "run", missing_pdftotext)

    frame, receipt = parse_prasa_transition_contracts(source)

    assert len(frame) >= 600
    assert frame["contract_id"].is_unique
    row = frame.loc[frame["contract_id"] == "2021-000162-G"].iloc[0]
    assert row["vendor_name"] == "Black & Veatch Puerto Rico, PSC"
    assert row["contract_value"] == "$125,275,430.00"
    assert receipt["duplicate_contract_ids"] == 0
