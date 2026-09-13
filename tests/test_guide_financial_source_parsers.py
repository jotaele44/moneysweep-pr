from __future__ import annotations

from scripts.scrape_ftz_board_pr import parse_zone
from scripts.scrape_ocif_guide_financial_classes import parse_page
from scripts.scrape_ocs_insurers import parse_annual_reports, parse_insurers


def test_ocif_parser_preserves_raw_fields_and_denominator():
    html = """
    <html><body>
      <table>
        <thead><tr>
          <th>Tipo de Ins.</th><th>Nombre de Ins.</th><th>DBA</th><th>Estatus</th>
          <th>Dirección</th><th>Teléfono</th><th>Fecha de Aprobación</th>
          <th>Número de Lic.</th><th>NMLS</th><th>Nombre de Contacto</th><th>CRD</th><th>Depositaria</th>
        </tr></thead>
        <tbody><tr>
          <td>ENTIDAD FINANCIERA INTERNACIONAL</td><td>ÁGUILA BANK, LLC</td><td></td><td>ACTIVA</td>
          <td>CALLE 1  SAN JUAN PR</td><td>787-000-0000</td><td>01/01/2026</td>
          <td>IFE-999</td><td></td><td>José Pérez</td><td></td><td>YES</td>
        </tr></tbody>
      </table>
      <div>Filas: 1 de 1 Página: 1 de 1</div>
    </body></html>
    """
    rows, meta = parse_page(
        html,
        source_page=1,
        source_url="https://example.test/ocif",
        retrieved_at="2026-08-26T00:00:00+00:00",
    )
    assert meta == {"page_rows": 1, "total_rows": 1, "page": 1, "total_pages": 1}
    assert len(rows) == 1
    assert rows[0]["institution_name_raw"] == "ÁGUILA BANK, LLC"
    assert rows[0]["license_number_raw"] == "IFE-999"
    assert rows[0]["contact_name_raw"] == "José Pérez"
    assert len(rows[0]["source_record_id"]) == 64


def test_ocs_current_and_annual_are_distinct_observation_grains():
    current_html = """
    <html><body>
      <div class='card'><img alt='Popular Re, Inc.'/><a href='https://popular.example'>Website</a></div>
      <div class='card'><img alt='Triple-S Vida, Inc.'/><a href='https://triples.example'>Website</a></div>
    </body></html>
    """
    current = parse_insurers(
        current_html,
        source_url="https://example.test/insurers",
        retrieved_at="2026-08-26T00:00:00+00:00",
    )
    assert [row["insurer_name_raw"] for row in current] == [
        "Popular Re, Inc.",
        "Triple-S Vida, Inc.",
    ]

    annual_html = """
    <html><body>
      <h2>2025</h2>
      <div><a href='/files/popular-re-2025.pdf'>Popular Re, Inc.</a></div>
      <h2>2024</h2>
      <div><a href='/files/popular-re-2024.pdf'>Popular Re, Inc.</a></div>
    </body></html>
    """
    annual = parse_annual_reports(
        annual_html,
        source_url="https://example.test/annual",
        retrieved_at="2026-08-26T00:00:00+00:00",
    )
    assert [(row["report_year_raw"], row["insurer_name_raw"]) for row in annual] == [
        ("2025", "Popular Re, Inc."),
        ("2024", "Popular Re, Inc."),
    ]
    assert annual[0]["source_record_id"] != annual[1]["source_record_id"]


def test_ocs_annual_parser_accepts_official_cms_item_links():
    html = """
    <html><body>
      <h2>2025</h2>
      <div><a href='/informes-anuales/2025-popular-re-inc-j4idh'>Popular Re, Inc.</a></div>
      <div><a href='/informes-anuales/triple-s-vida-inc-32ejq2025'>Triple-S Vida, Inc.</a></div>
      <div><a href='/unrelated/2025-item'>Not an annual report</a></div>
    </body></html>
    """
    rows = parse_annual_reports(
        html,
        source_url="https://www.ocs.pr.gov/regulados/informes-anuales",
        retrieved_at="2026-08-26T00:00:00+00:00",
    )
    assert [(row["report_year_raw"], row["insurer_name_raw"]) for row in rows] == [
        ("2025", "Popular Re, Inc."),
        ("2025", "Triple-S Vida, Inc."),
    ]
    assert all("/informes-anuales/" in row["report_url"] for row in rows)


def test_ftz_parser_verifies_zone_and_preserves_site_rows():
    html = """
    <html><body>
      <div>Zone Number</div><div>061</div>
      <div>Approved on Date</div><div>10/20/1980</div>
      <div>Grantee</div><div>Department of Economic Development and Commerce</div>
      <div>Location</div><div>San Juan</div>
      <div>Status</div><div>Active</div>
      <div>Port of Entry</div><div>PR, San Juan</div>
      <div>Activation Limit</div><div>1821.07</div>
      <div>Total Activated Acres</div><div>343.66</div>
      <table>
        <thead><tr><th>Site Number</th><th>Site Name</th><th>Status</th><th>Activated Acres</th><th>Sunset/Expiration/Lapse Date</th></tr></thead>
        <tbody><tr><td>001</td><td>International Trade Center</td><td>Active</td><td>148.92</td><td></td></tr></tbody>
      </table>
    </body></html>
    """
    rows = parse_zone(
        html,
        detail_id=239,
        source_url="https://example.test/ftz/239",
        retrieved_at="2026-08-26T00:00:00+00:00",
    )
    assert len(rows) == 2
    assert rows[0]["record_type"] == "zone"
    assert rows[0]["zone_number_raw"] == "061"
    assert rows[1]["record_type"] == "site"
    assert rows[1]["site_number_raw"] == "001"
    assert rows[1]["site_name_raw"] == "International Trade Center"
