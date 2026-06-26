from scripts.probe_legislapr_detail_page import (
    legislapr_detail_url,
    normalize_measure_id,
    probe_measure,
    promotion_state,
)


def test_normalize_measure_id_variants():
    assert normalize_measure_id("PS%20782") == "PS 782"
    assert normalize_measure_id("pc-1207") == "PC 1207"
    assert normalize_measure_id("  rcs   12 ") == "RCS 12"


def test_detail_url_quotes_measure_id_space():
    assert legislapr_detail_url("PS 782") == "https://www.legislapr.com/bills/PS%20782"


def test_promotion_state_requires_openstates_and_official_document():
    assert promotion_state(None, None) == "discovery_only_hold"
    assert promotion_state("https://openstates.org/pr/bills/2025-2026/PS782/", None) == "partially_confirmed_hold"
    assert promotion_state(None, "https://sutra.oslpr.org/medidas/ps0782-25.doc") == "partially_confirmed_hold"
    assert (
        promotion_state(
            "https://openstates.org/pr/bills/2025-2026/PS782/",
            "https://sutra.oslpr.org/medidas/ps0782-25.doc",
        )
        == "cross_confirmed_ready"
    )


def test_probe_measure_extracts_cross_confirmation_and_fiscal_signal():
    html = """
    <html><body>
      <a href="https://openstates.org/pr/bills/2025-2026/PS782/">OpenStates</a>
      <a href="https://sutra.oslpr.org/medidas/ps0782-25.doc">Texto oficial</a>
      Para asignar fondos y ordenar reembolso a un municipio.
    </body></html>
    """
    record = probe_measure("PS 782", html=html)
    assert record.measure_id == "PS 782"
    assert record.openstates_url == "https://openstates.org/pr/bills/2025-2026/PS782/"
    assert record.official_document_url == "https://sutra.oslpr.org/medidas/ps0782-25.doc"
    assert record.fiscal_signal is True
    assert record.promotion_state == "cross_confirmed_ready"
