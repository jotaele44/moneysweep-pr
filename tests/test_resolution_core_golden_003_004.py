import json
from pathlib import Path

from moneysweep.capital_control.resolution_core import (
    Candidate,
    CertificationState,
    Contradiction,
    EvidenceBasis,
    adjudicate_contradiction,
    resolve_candidates,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "capital_control"


def _load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_golden_003_tamcor_bounded_arithmetic_and_zero_amendments() -> None:
    corpus = _load("golden_003_tamcor.json")
    assertions = {item["id"]: item for item in corpus["assertions"]}
    base = assertions["ocpr-base-arithmetic"]
    assert sum(base["base_amounts"]) == base["expected_total"] == 89903.0
    classes = assertions["ocpr-class-arithmetic"]
    assert sum(classes["transfer_amounts"]) == classes["expected_transfer_total"] == 62480.0
    assert (
        sum(classes["material_purchase_amounts"])
        == classes["expected_material_purchase_total"]
        == 27423.0
    )
    assert assertions["ocpr-2018-000297-A"]["increment"] == 0.0
    assert assertions["ocpr-2018-000297-B"]["increment"] == 0.0


def test_golden_003_tamcor_related_network_does_not_collapse_by_continuity() -> None:
    result = resolve_candidates(
        [
            Candidate(
                "Trujillo Alto Metal Corporation",
                EvidenceBasis.HISTORICAL_CONTINUITY_WITH_CORROBORATION,
                "shared operating history",
            ),
            Candidate(
                "TAMCOR Manufacturing Corp.",
                EvidenceBasis.HISTORICAL_CONTINUITY_WITH_CORROBORATION,
                "shared operating history",
            ),
            Candidate(
                "TAM Industries, Inc.",
                EvidenceBasis.HISTORICAL_CONTINUITY_WITH_CORROBORATION,
                "shared operating history",
            ),
        ]
    )
    assert result.state is CertificationState.UNRESOLVED
    assert result.selected_id is None
    assert len(result.candidates) == 3


def test_golden_003_tamcor_ddec_serial_supersession_is_preserved() -> None:
    corpus = _load("golden_003_tamcor.json")
    assertion = next(
        item for item in corpus["assertions"] if item["id"] == "ddec-39084-supersession"
    )
    contradiction = Contradiction(
        "TAMCOR_DDEC_39084",
        "SCHEMA",
        tuple(assertion["observations"]),
    )
    result = adjudicate_contradiction(
        contradiction,
        controlling_observation=assertion["controlling"],
        superseded_observations=tuple(assertion["expected_superseded"]),
        reason="direct workbook schema identifies Excel date serial",
    )
    assert result.state is CertificationState.PASS
    assert result.superseded_observations == ("39084 interpreted as decree number",)


def test_golden_004_prasa_jacobs_discovery_keys_stay_discovery_only() -> None:
    corpus = _load("golden_004_prasa_jacobs.json")
    assertion = next(
        item for item in corpus["assertions"] if item["id"] == "contract-id-discovery-keys"
    )
    for key in assertion["discovery_keys"]:
        result = resolve_candidates(
            [
                Candidate(
                    key,
                    EvidenceBasis.HEURISTIC_DISCOVERY_ONLY,
                    "archive keyword configuration",
                )
            ]
        )
        assert result.state is CertificationState.CANDIDATE_NOT_IDENTITY
        assert result.selected_id is None


def test_golden_004_prasa_jacobs_windows_are_bounded_not_universal() -> None:
    corpus = _load("golden_004_prasa_jacobs.json")
    assertion = next(
        item for item in corpus["assertions"] if item["id"] == "archive-harvester-denominator"
    )
    assert assertion["expected"] == "BOUNDED_DISCOVERY_WINDOW"
    assert len(assertion["windows"]) == 3
    assert {row["domain"] for row in assertion["windows"]} == {
        "acueductospr.com",
        "aaasubastas.com",
        "acueductos.pr.gov",
    }
