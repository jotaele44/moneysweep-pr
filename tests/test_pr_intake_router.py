from pathlib import Path

import pytest

from shared.pr_intake_router import (
    CONTRACT_REPO,
    SPIDERWEB_REPO,
    IntakeRouterError,
    load_router_config,
    route_raw_item,
    route_raw_items,
)


CONFIG_PATH = Path("config/pr_intake_domain_router.yaml")


def test_public_funding_routes_to_contract_sweeper():
    config = load_router_config(CONFIG_PATH)
    item = {
        "source_item_id": "RAW-001",
        "source_name": "Fortaleza",
        "source_url": "https://example.test/funding",
        "published_at": "2026-05-27",
        "discovered_at": "2026-05-27T12:00:00Z",
        "title": "Gobierno anuncia asignación de $5 millones para proyecto municipal",
        "summary": "Fondos asignados por agencia pública para reparación.",
        "evidence_tier": "T2",
        "confidence_level": "High",
    }

    result = route_raw_item(item, config)

    assert result.final_status == "routed_contract_sweeper"
    assert result.canonical_repo == CONTRACT_REPO
    assert result.contract_sweeper_derivative is not None
    assert result.spiderweb_pr_derivative is None
    assert "CS_PUBLIC_FUNDING" in result.matched_rules


def test_pure_spatial_routes_to_spiderweb_pr():
    config = load_router_config(CONFIG_PATH)
    item = {
        "source_item_id": "RAW-002",
        "source_name": "USGS",
        "source_url": "https://example.test/lidar",
        "published_at": "2026-05-27",
        "discovered_at": "2026-05-27T12:00:00Z",
        "title": "Nuevo dataset LiDAR y mapa de quebrada en Puerto Rico",
        "summary": "Dataset GIS con DEM para análisis de hidrología.",
        "location_text": "Puerto Rico",
        "evidence_tier": "T1",
        "confidence_level": "High",
    }

    result = route_raw_item(item, config)

    assert result.final_status == "routed_spiderweb_pr"
    assert result.canonical_repo == SPIDERWEB_REPO
    assert result.spiderweb_pr_derivative is not None
    assert result.contract_sweeper_derivative is None
    assert "SW_SUBSURFACE_HYDRO" in result.matched_rules


def test_infrastructure_with_funding_dual_routes_contract_primary():
    config = load_router_config(CONFIG_PATH)
    item = {
        "source_item_id": "RAW-003",
        "source_name": "DTOP",
        "source_url": "https://example.test/bridge-award",
        "published_at": "2026-05-27",
        "discovered_at": "2026-05-27T12:00:00Z",
        "title": "Aviso de adjudicación para puente con inversión de $10 millones",
        "summary": "Proyecto de infraestructura en puente municipal.",
        "municipality_name": "Ponce",
        "evidence_tier": "T2",
        "confidence_level": "High",
    }

    result = route_raw_item(item, config)

    assert result.final_status == "dual_routed_contract_primary"
    assert result.canonical_repo == CONTRACT_REPO
    assert result.derivative_repo == SPIDERWEB_REPO
    assert result.contract_sweeper_derivative is not None
    assert result.spiderweb_pr_derivative is not None


def test_unmatched_item_becomes_manual_review_required():
    config = load_router_config(CONFIG_PATH)
    item = {
        "source_item_id": "RAW-004",
        "source_name": "Unknown",
        "source_url": "https://example.test/unclear",
        "published_at": "2026-05-27",
        "discovered_at": "2026-05-27T12:00:00Z",
        "title": "Comunicado general sin detalle operativo",
        "summary": "No contiene señales configuradas.",
        "evidence_tier": "T4",
        "confidence_level": "Low",
    }

    result = route_raw_item(item, config)

    assert result.final_status == "manual_review_required"
    assert result.canonical_repo is None
    assert result.review_reason


def test_spatial_record_without_location_fails_strict_gate():
    config = load_router_config(CONFIG_PATH)
    item = {
        "source_item_id": "RAW-005",
        "source_name": "NOAA",
        "source_url": "https://example.test/weather",
        "published_at": "2026-05-27",
        "discovered_at": "2026-05-27T12:00:00Z",
        "title": "NOAA publica dataset de weather monitoring",
        "summary": "Dataset ambiental sin location_text ni geocoding.",
        "evidence_tier": "T1",
        "confidence_level": "Medium",
    }

    with pytest.raises(IntakeRouterError):
        route_raw_item(item, config, strict=True)

    non_strict = route_raw_item(item, config, strict=False)
    assert non_strict.validation_errors


def test_access_status_forces_zero_loss_terminal_status():
    config = load_router_config(CONFIG_PATH)
    item = {
        "source_item_id": "RAW-006",
        "source_name": "Blocked Source",
        "source_url": "https://example.test/paywall",
        "published_at": "2026-05-27",
        "discovered_at": "2026-05-27T12:00:00Z",
        "title": "Potentially relevant item",
        "archive_status": "metadata_only",
    }

    result = route_raw_item(item, config)

    assert result.final_status == "metadata_only_archived"
    assert result.canonical_repo is None


def test_route_raw_items_assigns_final_status_to_all():
    config = load_router_config(CONFIG_PATH)
    items = [
        {
            "source_item_id": "RAW-007",
            "source_name": "ASG",
            "source_url": "https://example.test/rfp",
            "title": "RFP de procurement para contrato de servicios",
            "published_at": "2026-05-27",
            "discovered_at": "2026-05-27T12:00:00Z",
        },
        {
            "source_item_id": "RAW-008",
            "source_name": "CariCOOS",
            "source_url": "https://example.test/dataset",
            "title": "CariCOOS dataset de monitoreo costero",
            "location_text": "San Juan, Puerto Rico",
            "published_at": "2026-05-27",
            "discovered_at": "2026-05-27T12:00:00Z",
        },
    ]

    results = route_raw_items(items, config)

    assert len(results) == 2
    assert all(result.final_status for result in results)


def test_spiderweb_derivative_carries_geocode_and_asset_enrichment():
    """Enrichment: when the raw item carries location/asset fields, the
    spiderweb-pr derivative passes them through so the spatial lane can place
    the record on the map instead of queuing it for manual geocoding."""
    config = load_router_config(CONFIG_PATH)
    item = {
        "source_item_id": "RAW-ENRICH-1",
        "source_name": "USGS",
        "source_url": "https://example.test/lidar-ponce",
        "published_at": "2026-05-27",
        "discovered_at": "2026-05-27T12:00:00Z",
        "title": "Nuevo dataset LiDAR de quebrada en Ponce",
        "summary": "Dataset GIS con DEM para análisis de hidrología.",
        "latitude": 18.0111,
        "longitude": -66.6141,
        "location_text": "Ponce, Puerto Rico",
        "municipality": "Ponce",
        "asset_type": "hydrology_dataset",
        "dataset_type": "lidar_dem",
        "file_format": "GeoTIFF",
        "agency": "USGS",
    }

    result = route_raw_item(item, config)
    deriv = result.spiderweb_pr_derivative

    assert deriv is not None
    assert deriv["latitude"] == 18.0111
    assert deriv["longitude"] == -66.6141
    assert deriv["location_text"] == "Ponce, Puerto Rico"
    assert deriv["municipality_name"] == "Ponce"   # aliased from `municipality`
    assert deriv["asset_type"] == "hydrology_dataset"
    assert deriv["dataset_type"] == "lidar_dem"
    assert deriv["file_format"] == "GeoTIFF"
    assert deriv["agency_entity"] == "USGS"          # aliased from `agency`


def test_spiderweb_derivative_enrichment_absent_degrades_gracefully():
    """When the raw item has no location/asset fields, the enrichment keys are
    present but empty/None (the spatial lane then queues for manual geocoding)."""
    config = load_router_config(CONFIG_PATH)
    item = {
        "source_item_id": "RAW-ENRICH-2",
        "source_name": "USGS",
        "source_url": "https://example.test/lidar-nogeo",
        "published_at": "2026-05-27",
        "discovered_at": "2026-05-27T12:00:00Z",
        "title": "Nuevo dataset LiDAR sin coordenadas",
        "summary": "Dataset GIS con DEM para análisis de hidrología.",
        "location_text": "Puerto Rico",  # keeps the spatial gate satisfied
    }

    result = route_raw_item(item, config)
    deriv = result.spiderweb_pr_derivative

    assert deriv is not None
    for key in ("latitude", "longitude", "municipality_name", "asset_type",
                "dataset_type", "file_format", "agency_entity"):
        assert key in deriv
        assert not deriv[key]
