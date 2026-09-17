from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "manifests" / "macro" / "jp_questionnaire_universe_v1.json"


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_official_inventory_corroborates_income_net_collection_architecture() -> None:
    evidence = _manifest()["official_form_inventory_corroboration"]
    income_net = evidence["income_net_architecture"]

    assert evidence["evidence_state"] == "AUTHORITATIVE_SUPPORTING_NOT_CURRENT_MANIFESTATION_IDENTITY"
    assert income_net["form_type"] == "Estado de Ingresos y Gastos diferenciado por industria"
    assert income_net["periodicity"] == "ANNUAL"
    assert "IP-310" in income_net["form_codes_observed"]
    assert "IP-520" in income_net["form_codes_observed"]


def test_current_listing_and_historical_inventory_are_not_collapsed_into_identity() -> None:
    evidence = _manifest()["official_form_inventory_corroboration"]
    boundary = evidence["identity_boundary"]

    assert "does not prove" in boundary.lower()
    assert "currently active" in boundary.lower()
    assert "respondent microdata" in boundary.lower()


def test_bop_forms_are_preserved_as_distinct_collection_domain() -> None:
    forms = _manifest()["official_form_inventory_corroboration"]["bop_and_other_forms_observed"]
    by_code = {row["code"]: row for row in forms}

    assert by_code["JP-362"]["unit"] == "Balanza de Pagos"
    assert by_code["JP-544"]["unit"] == "Balanza de Pagos"
    assert by_code["JP-536"]["unit"] == "Ingreso Neto"
    assert by_code["JP-316"]["unit"] == "Ingreso Neto"


def test_questionnaire_discovery_does_not_promote_sector_amounts() -> None:
    interpretation = _manifest()["interpretation"]

    assert interpretation["content_review_state"] == "BLOCKED_ARTIFACT_RETRIEVAL"
    assert interpretation["public_source_exhaustion"] == "OPEN"
    assert "does not prove" in interpretation["what_discovery_does_not_prove"].lower()
    assert "fy2025" in interpretation["what_discovery_does_not_prove"].lower()


def test_broken_manifestation_is_not_source_absence() -> None:
    broken = next(
        row for row in _manifest()["forms"] if row["code"] == "JP-560-63210"
    )

    assert broken["document_state"] == "LISTED_BUT_CLICKED_MANIFESTATION_404"
    assert broken["source_absence"] is False
