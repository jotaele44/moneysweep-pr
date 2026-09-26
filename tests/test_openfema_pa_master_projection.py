from __future__ import annotations

import pandas as pd
import pytest

from scripts.download_openfema_pa_projects import (
    LEGACY_MASTER_COLUMNS,
    _legacy_master_from_v2,
)

pytestmark = pytest.mark.unit


def test_live_v2_projection_matches_canonical_fema_master_schema() -> None:
    source = pd.DataFrame(
        [
            {
                "disaster_number": "4339",
                "pw_number": "1234",
                "applicant_name": "Municipio de San Juan",
                "county": "San Juan",
                "application_title": "Permanent work",
                "damage_category": "E",
                "project_amount": 125000.0,
                "federal_share_obligated": 112500.0,
                "pw_date": "2025-10-15T00:00:00.000Z",
            },
            {
                "disaster_number": "4473",
                "pw_number": "",
                "applicant_name": "Puerto Rico agency",
                "county": "Bayamón",
                "application_title": "",
                "damage_category": "B",
                "project_amount": 0,
                "federal_share_obligated": 5000.0,
                "pw_date": "2025-07-01",
            },
        ]
    )

    projected = _legacy_master_from_v2(source)

    assert list(projected.columns) == LEGACY_MASTER_COLUMNS
    assert len(projected) == 2
    assert projected.loc[0, "award_id"] == "FEMA-PA-4339-1234"
    assert projected.loc[0, "obligated_amount"] == 125000.0
    assert projected.loc[0, "fiscal_year"] == 2026
    assert projected.loc[1, "award_id"] == "FEMA-PA-4473"
    assert projected.loc[1, "obligated_amount"] == 5000.0
    assert projected.loc[1, "description"] == "B"
    assert set(projected["pop_state"]) == {"PR"}
    assert set(projected["source_dataset"]) == {"fema_pa"}
    assert set(projected["award_category"]) == {"disaster_assistance"}
