import copy

import pytest

from tools.build_certification_blocker_graph import build_graph


CONFIG = {
    "gates": [
        {"id": "G0", "blocking": True, "depends_on": []},
        {"id": "G1", "blocking": True, "depends_on": ["G0"]},
        {"id": "G2", "blocking": True, "depends_on": ["G1"]},
    ]
}


def _report() -> dict:
    return {
        "certification_state": "NON_PRODUCTION_DIAGNOSTIC",
        "production_eligible": False,
        "scope": {"commit_sha": "a" * 40},
        "gates": [
            {"id": "G0", "state": "PASS", "blockers": []},
            {"id": "G1", "state": "FAIL", "blockers": ["cor3", "hud_drgr_authorized"]},
            {"id": "G2", "state": "BLOCKED", "blockers": ["downstream_residue"]},
        ],
    }


def test_active_frontier_excludes_downstream_dependency_blocked_gates() -> None:
    graph = build_graph(_report(), CONFIG)
    gates = {gate["id"]: gate for gate in graph["gates"]}

    assert graph["summary"]["active_frontier"] == ["G1"]
    assert graph["summary"]["dependency_blocked_gates"] == ["G2"]
    assert gates["G1"]["actionable"] is True
    assert gates["G2"]["actionable"] is False
    assert gates["G2"]["dependency_blockers"] == ["G1"]


def test_direct_blockers_are_preserved_without_collapsing_values() -> None:
    graph = build_graph(_report(), CONFIG)

    values = {blocker["value"] for blocker in graph["blockers"]}
    assert values == {"cor3", "hud_drgr_authorized", "downstream_residue"}
    assert graph["summary"]["direct_blocker_total"] == 3
    assert len({blocker["id"] for blocker in graph["blockers"]}) == 3


def test_output_is_deterministic_for_same_report_and_config() -> None:
    first = build_graph(_report(), CONFIG)
    second = build_graph(copy.deepcopy(_report()), copy.deepcopy(CONFIG))

    assert first == second


def test_gate_denominator_mismatch_fails_closed() -> None:
    report = _report()
    report["gates"] = report["gates"][:-1]

    with pytest.raises(RuntimeError, match="Gate denominator mismatch"):
        build_graph(report, CONFIG)


def test_unknown_dependency_fails_closed() -> None:
    config = copy.deepcopy(CONFIG)
    config["gates"][1]["depends_on"] = ["G404"]

    with pytest.raises(RuntimeError, match="unknown dependencies"):
        build_graph(_report(), config)
