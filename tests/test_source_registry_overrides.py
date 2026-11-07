from __future__ import annotations

import json
from pathlib import Path

import pytest

from moneysweep.runtime.source_registry import (
    _apply_registry_overrides,
    all_sources,
    source_by_id,
)

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[1]


def test_overrides_preserve_source_denominator_and_required_count() -> None:
    base = json.loads((ROOT / "registries/source_registry.json").read_text(encoding="utf-8"))
    effective = all_sources(ROOT)

    assert len(effective) == len(base["sources"]) + sum(
        len(json.loads(path.read_text(encoding="utf-8")).get("sources", []))
        for path in (ROOT / "registries/source_registry_extensions").glob("*.json")
    )
    assert sum(source.get("required", False) for source in effective) == 16


def test_wave0_provenance_corrections_are_effective() -> None:
    cor3 = source_by_id("cor3", ROOT)
    assert cor3 is not None
    assert cor3["producer_script"] == "scripts/download_cor3.py"
    assert cor3["authorized_manual_ingest_script"] == "scripts/ingest_cor3.py"
    assert cor3["live_endpoint_status"] == "UNVERIFIED_BEST_EFFORT"

    cabilderos = source_by_id("pr_cabilderos", ROOT)
    assert cabilderos is not None
    assert cabilderos["official_custodian"] == "Puerto Rico Department of Justice"
    assert cabilderos["endpoint_url"].startswith("https://www.justicia.pr.gov/")

    grants = source_by_id("grants_gov", ROOT)
    assert grants is not None
    assert grants["endpoint_url"] == ("https://api.usaspending.gov/api/v2/bulk_download/awards/")
    assert grants["source_identity_status"] == ("HISTORICAL_ID_PRESERVED_ENDPOINT_CORRECTED")


def test_override_rejects_unknown_source() -> None:
    with pytest.raises(ValueError, match="unknown source"):
        _apply_registry_overrides(
            [{"source_id": "known", "required": False}],
            [{"source_id": "unknown", "endpoint_url": "https://example.invalid"}],
        )


def test_override_cannot_change_required_denominator() -> None:
    with pytest.raises(ValueError, match="immutable field required"):
        _apply_registry_overrides(
            [{"source_id": "known", "required": False}],
            [{"source_id": "known", "required": True}],
        )
