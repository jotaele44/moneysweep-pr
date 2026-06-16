from scripts.alerts.alert_event_schema import AlertLevel, ProjectStage
from scripts.alerts.github_issue_exporter import issue_body, issue_labels, issue_title
from scripts.alerts.project_signal_detector import detect_project_signals
from scripts.alerts.spiderweb_exporter import build_spiderweb_packet

WATCHLIST = [
    {
        "project_id": "PRJ_ESENCIA",
        "canonical_name": "Proyecto Esencia",
        "aliases": ["Proyecto Esencia", "Esencia"],
        "locations": {"municipios": ["Cabo Rojo", "Lajas"], "regions": []},
        "entity_terms": ["resort", "master plan"],
        "spiderweb_trigger_threshold": 55,
    },
    {
        "project_id": "PRJ_PR100",
        "canonical_name": "PR100",
        "aliases": ["PR 100", "Puerto Rico 100"],
        "locations": {"municipios": [], "regions": ["islandwide"]},
        "entity_terms": ["grid resilience", "renewable energy"],
        "spiderweb_trigger_threshold": 55,
    },
]

THRESHOLDS = {
    "thresholds": {"watch": 35, "review": 55, "urgent": 75, "critical": 90},
    "scoring": {
        "exact_project_name_match": 30,
        "alias_match": 20,
        "official_procurement_source": 20,
        "permit_land_use_environmental_source": 20,
        "budget_funding_bond_source": 15,
        "vendor_recurrence": 15,
        "matching_municipio_or_aoi": 10,
        "matching_agency": 10,
        "matching_parcel_coordinate_facility": 10,
        "amount_exceeds_threshold": 10,
        "two_source_families": 10,
        "three_or_more_source_families": 15,
        "stage_advance": 10,
        "media_only_penalty": -20,
    },
    "amount_thresholds": {"default_major_amount": 1_000_000},
}


def test_proyecto_esencia_review_plus_triggers_spiderweb():
    records = [
        {
            "award_id": "A-1",
            "source_dataset": "compras_pr",
            "award_date": "2026-06-16",
            "awarding_agency": "DDEC",
            "recipient_name": "Example Contractor LLC",
            "obligated_amount": "2450000",
            "municipio": "Cabo Rojo",
            "description": "Engineering and site work for Proyecto Esencia resort master plan.",
        }
    ]
    events = detect_project_signals(records, watchlist=WATCHLIST, thresholds=THRESHOLDS)
    assert len(events) == 1
    event = events[0]
    assert event.project_id == "PRJ_ESENCIA"
    assert event.alert_level in {AlertLevel.REVIEW, AlertLevel.URGENT, AlertLevel.CRITICAL}
    assert event.requires_spiderweb is True
    assert event.project_stage >= ProjectStage.PROFESSIONAL_SERVICES


def test_pr100_budget_signal_detects_project():
    records = [
        {
            "award_id": "P-1",
            "source_dataset": "doe",
            "awarding_agency": "DOE",
            "recipient_name": "Grid Vendor LLC",
            "obligated_amount": "1500000",
            "description": "PR100 grid resilience renewable energy transmission study.",
        }
    ]
    events = detect_project_signals(records, watchlist=WATCHLIST, thresholds=THRESHOLDS)
    assert len(events) == 1
    assert events[0].project_id == "PRJ_PR100"
    assert "budget_funding_bond_source" in events[0].trigger_reason


def test_generic_false_positive_does_not_alert():
    records = [
        {
            "award_id": "F-1",
            "source_dataset": "media",
            "description": "The essence of good procurement is transparency.",
        }
    ]
    events = detect_project_signals(records, watchlist=WATCHLIST, thresholds=THRESHOLDS)
    assert events == []


def test_github_and_spiderweb_exports_are_deterministic():
    record = {
        "award_id": "A-2",
        "source_dataset": "usaspending",
        "awarding_agency": "DDEC",
        "recipient_name": "Example Contractor LLC",
        "obligated_amount": "2450000",
        "municipio": "Cabo Rojo",
        "description": "Proyecto Esencia construction procurement package.",
    }
    event = detect_project_signals([record], watchlist=WATCHLIST, thresholds=THRESHOLDS)[0]
    assert "PROJECT ALERT" in issue_title(event)
    assert "requires-spiderweb" in issue_labels(event)
    assert "## Project" in issue_body(event)
    packet = build_spiderweb_packet(event)
    assert packet["project_id"] == "PRJ_ESENCIA"
    assert packet["minimum_graph_depth"] == 2
