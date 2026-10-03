import pytest

from scripts.download_prasa_contracts import normalize_amount, parse_extracted_table

pytestmark = pytest.mark.unit


def test_prasa_transition_table_maps_official_columns_to_ingest_schema() -> None:
    table = [
        [
            "Número de\nContrato",
            "Contratista",
            "Fecha de\nOtorgación",
            "Fecha de\nInicio",
            "Fecha de\nTerminación",
            "Cuantía",
            "Tipo de Servicio",
            "Comentarios",
        ],
        [
            "2021-000162-G",
            "Black & Veatch Puerto Rico, PSC",
            "4-ene.-24",
            "4-ene.-24",
            "30-jun.-25",
            "$125,275,430.00",
            "Servicio gerencia de proyectos",
            "",
        ],
        ["Art. 9 (a) 12", "3", "", "", "", "", "", ""],
    ]

    rows = parse_extracted_table(table)

    assert len(rows) == 1
    assert rows[0]["Número de Contrato"] == "2021-000162-G"
    assert rows[0]["Contratista"] == "Black & Veatch Puerto Rico, PSC"
    assert rows[0]["Monto"] == "125275430.00"
    assert rows[0]["Tipo de Contrato"] == "Servicio gerencia de proyectos"
    assert rows[0]["Estado"] == "Vigente al 2024-09-24"


def test_prasa_amount_normalization_preserves_zero_and_parenthesized_negative() -> None:
    assert normalize_amount("$0.00") == "0.00"
    assert normalize_amount("($1,250.50)") == "-1250.50"
