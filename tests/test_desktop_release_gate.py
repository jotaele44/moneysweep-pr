"""Publication gate for the desktop bundle (``.github/workflows/desktop-build.yml``).

A ``desktop-v*`` tag is the only route in this repo that creates a public GitHub
Release, and it is reached by neither ``production-status-gate.yml`` nor
``release-tag.yml`` — both are scoped to pushes and pull requests. The workflow
therefore carries its own check, and these tests guard the two ways that check
could quietly stop working: by drifting from the status vocabulary it hardcodes,
or by being reordered after the step it is meant to gate.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from moneysweep.validation import production_status as ps

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ".github/workflows/desktop-build.yml"
TAG_CONDITION = "startsWith(github.ref, 'refs/tags/desktop-v')"
GATE = "Refuse public release unless production-validated"
ATTACH = "Attach to release"
INSTALL = "Install Python dependencies"


@pytest.fixture(scope="module")
def steps() -> list[dict]:
    path = REPO_ROOT / WORKFLOW
    assert path.exists(), f"missing desktop build workflow {WORKFLOW}"
    return yaml.safe_load(path.read_text(encoding="utf-8"))["jobs"]["build"]["steps"]


def _index(steps: list[dict], name: str) -> int:
    for i, step in enumerate(steps):
        if step.get("name") == name:
            return i
    raise AssertionError(f"no step named {name!r} in {WORKFLOW}")


@pytest.mark.unit
def test_gate_runs_before_the_release_is_attached(steps):
    # Same job, so a failing gate means the attach never runs. Ordering is the
    # whole mechanism; a reorder would silently disarm it.
    assert _index(steps, GATE) < _index(steps, ATTACH)


@pytest.mark.unit
def test_gate_and_attach_share_the_tag_condition(steps):
    # If the gate were narrower than the attach, a tag could reach the publish
    # step ungated.
    assert steps[_index(steps, GATE)]["if"] == TAG_CONDITION
    assert steps[_index(steps, ATTACH)]["if"] == TAG_CONDITION


@pytest.mark.unit
def test_gate_allowlists_only_the_release_ready_status(steps):
    # An allowlist, so a missing key, a typo, or PARTIAL_PRODUCTION all stop.
    # PARTIAL_PRODUCTION is legitimately produced when the WARN gates fail and
    # means "major layers still require validation" — not release-ready.
    run = steps[_index(steps, GATE)]["run"]
    assert f'RELEASE_READY = "{ps.STATUS_VALIDATED}"' in run, (
        "workflow hardcodes a status that no longer matches "
        "moneysweep.validation.production_status.STATUS_VALIDATED"
    )
    assert "state != RELEASE_READY" in run, "gate must allowlist, not denylist"
    for rejected in (ps.STATUS_NON_PRODUCTION, ps.STATUS_PARTIAL):
        assert rejected != ps.STATUS_VALIDATED
        assert f'"{rejected}"' not in run, (
            f"{rejected} should be rejected by the allowlist, not named in it"
        )


@pytest.mark.unit
def test_gate_runs_on_every_matrix_os(steps):
    # The job matrix includes windows-latest, where bash is not a safe default.
    assert steps[_index(steps, GATE)]["shell"] == "python"


@pytest.mark.unit
def test_vcs_dependency_install_enables_windows_long_paths(steps):
    install = steps[_index(steps, INSTALL)]
    assert install["env"] == {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "core.longpaths",
        "GIT_CONFIG_VALUE_0": "true",
    }


@pytest.mark.unit
def test_committed_status_would_block_a_release_today():
    # The repo is intentionally paused; if this ever flips, it should be a
    # deliberate act recorded in docs/RESUMPTION_CHECKLIST.md, not a surprise.
    status = json.loads(
        (REPO_ROOT / "data/exports/production_status.json").read_text(encoding="utf-8")
    )
    assert status["production_status"] != ps.STATUS_VALIDATED
