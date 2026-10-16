from pathlib import Path

import pytest

from scripts.download_cabilderos import parse_registry_html

pytestmark = pytest.mark.unit
FIXTURE = Path(__file__).parent / "fixtures/cabilderos_registry.html"


def test_official_registry_parser_expands_clients_and_preserves_registration() -> None:
    report = parse_registry_html(FIXTURE.read_text(encoding="utf-8"))

    assert report["registry_rows"] == 2
    assert report["unique_registrations"] == 2
    assert report["unique_lobbyists"] == 2
    assert report["client_relationships"] == 3
    assert report["raw_csv_rows"] == 3

    rows = report["rows"]
    assert {row["registro_cabildero_num"] for row in rows} == {
        "2026Q1-00351",
        "2026Q4-00345",
    }
    assert {row["registration_year"] for row in rows} == {"2026"}
    assert {row["client_name"] for row in rows} == {
        "Humana Management Services",
        "Fresenius Medical Care Puerto Rico",
        "VAX DEVELOPMENT GROUP",
    }
    first = next(row for row in rows if row["registro_cabildero_num"] == "2026Q1-00351")
    assert first["certificate_url"].endswith("/Lobbyist/Certify/fixture-001")


def test_registry_parser_fails_closed_when_authoritative_table_shape_is_missing() -> None:
    with pytest.raises(RuntimeError, match="expected headers"):
        parse_registry_html(
            "<html><body><table><tr><td>not the registry</td></tr></table></body></html>"
        )
