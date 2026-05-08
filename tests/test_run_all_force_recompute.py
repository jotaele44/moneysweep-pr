"""Unit tests for run_all recompute guard helper."""

from run_all import _call_step


def test_call_step_forwards_force_when_supported():
    seen = {}

    def _step(root=None, force=False):
        seen["root"] = root
        seen["force"] = force
        return {"ok": True}

    result = _call_step(_step, force_recompute=True, root="repo")

    assert result == {"ok": True}
    assert seen["root"] == "repo"
    assert seen["force"] is True


def test_call_step_does_not_override_explicit_force_kwarg():
    seen = {}

    def _step(force=False):
        seen["force"] = force
        return force

    result = _call_step(_step, force_recompute=True, force=False)

    assert result is False
    assert seen["force"] is False


def test_call_step_skips_force_for_functions_without_force_param():
    seen = {}

    def _step(root=None):
        seen["root"] = root
        return 7

    result = _call_step(_step, force_recompute=True, root="workspace")

    assert result == 7
    assert seen["root"] == "workspace"

