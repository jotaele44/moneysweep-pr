from __future__ import annotations

import pytest

from tools.build_keyless_execution_waves import PlanError, build

pytestmark = pytest.mark.unit


def row(source_id: str, *, key: str = "", trigger: str = "schedule",
        automatable: str = "True", ready: str = "True", present: str = "0",
        expected: str = "1") -> dict[str, str]:
    return {
        "source_id": source_id,
        "required": "False",
        "required_secret": key,
        "trigger_type": trigger,
        "automatable": automatable,
        "ready": ready,
        "producer_script": f"scripts/{source_id}.py",
        "path_type": "api_producer",
        "outputs_present_count": present,
        "expected_outputs_count": expected,
    }


def test_partition_and_wave_ordering() -> None:
    report = build([
        row("a"), row("b", trigger="manual"), row("c", trigger="on_drop"),
        row("d", trigger="dependency"), row("e", key="TOKEN"),
    ])
    assert report["automatable_total"] == 5
    assert report["keyless_total"] == 4
    assert report["credential_gated_total"] == 1
    assert report["wave_counts"] == {
        "W1_SCHEDULE_INDEPENDENT": 1,
        "W2_OPERATOR_TRIGGERED": 2,
        "W3_DEPENDENCY_GATED": 1,
    }
    assert report["waves"]["W3_DEPENDENCY_GATED"][0]["dependency_order_state"].startswith("UNRESOLVED")


def test_reported_outputs_never_become_execution_evidence() -> None:
    report = build([row("a", present="1", expected="1")])
    item = report["waves"]["W1_SCHEDULE_INDEPENDENT"][0]
    assert item["reported_outputs_present_count"] == 1
    assert item["reported_output_presence_is_execution_evidence"] is False
    assert report["invariants"]["readiness_is_execution_evidence"] is False


def test_credential_gated_is_not_in_keyless_waves() -> None:
    report = build([row("a", key="FEC_API_KEY"), row("b")])
    assert [x["source_id"] for x in report["credential_gated"]] == ["a"]
    wave_ids = {x["source_id"] for values in report["waves"].values() for x in values}
    assert wave_ids == {"b"}


@pytest.mark.parametrize("rows", [
    [row("a"), row("a")],
    [row("a", ready="False")],
    [row("a", trigger="mystery")],
    [row("a", present="2", expected="1")],
])
def test_fail_closed_on_identity_readiness_trigger_or_arithmetic(rows) -> None:
    with pytest.raises(PlanError):
        build(rows)


def test_nonautomatable_rows_do_not_enter_partition() -> None:
    report = build([row("a"), row("manual", automatable="False", ready="False")])
    assert report["automatable_total"] == 1
    assert report["keyless_total"] == 1


def test_invalid_boolean_is_not_truthy_by_accident() -> None:
    with pytest.raises(PlanError, match="invalid_boolean"):
        build([row("a", ready="maybe")])
