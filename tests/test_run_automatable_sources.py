"""Tests for the live-fetch runner (scripts.run_automatable_sources).

Hermetic: egress and producer execution are stubbed via monkeypatch, so selection,
the egress-blocked skip, and per-source result capture are exercised without network.
"""

from __future__ import annotations

import types

import pytest

import scripts.run_automatable_sources as mod
from scripts.run_automatable_sources import run, run_one, select_sources

pytestmark = pytest.mark.unit


def test_select_defaults_to_automatable_only():
    sources = [
        {"source_id": "api_one", "family": "federal", "producer_script": "scripts/a.py"},
        {"source_id": "manual_one", "family": "territorial", "producer_script": "scripts/b.py"},
    ]
    # api_one -> api_producer (automatable); manual_one -> manual_export (not).
    classes = {"api_one": "api_producer", "manual_one": "manual_export"}
    orig = mod._classify
    mod._classify = lambda s: classes[s["source_id"]]
    try:
        picked = [
            s["source_id"] for s in select_sources(sources, source=None, family=None, only=None)
        ]
    finally:
        mod._classify = orig
    assert picked == ["api_one"]


def test_explicit_only_bypasses_automatable_filter():
    sources = [
        {"source_id": "manual_one", "family": "territorial", "producer_script": "scripts/b.py"}
    ]
    picked = [
        s["source_id"]
        for s in select_sources(sources, source=None, family=None, only=["manual_one"])
    ]
    assert picked == ["manual_one"]  # ran despite being non-automatable


def test_run_skips_producers_when_egress_blocked(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "run_checks", lambda endpoints: {"ok": False, "blocked": endpoints})
    called = {"n": 0}
    monkeypatch.setattr(mod, "run_one", lambda *a, **k: called.__setitem__("n", called["n"] + 1))
    monkeypatch.setattr(
        mod,
        "load_source_registry",
        lambda root: {"sources": [{"source_id": "x", "producer_script": "p.py"}]},
    )
    monkeypatch.setattr(
        mod, "select_sources", lambda s, **k: s["sources"] if isinstance(s, dict) else s
    )
    # Force a non-empty selection regardless of classifier.
    monkeypatch.setattr(mod, "_classify", lambda s: "api_producer")

    result = run(root=tmp_path, require_egress=True)
    assert result["status"] == "egress_blocked"
    assert result["egress_ok"] is False
    assert called["n"] == 0  # no producer invoked


def test_run_one_captures_producer_error(tmp_path):
    boom = types.ModuleType("boom_mod")

    def run(root=None):  # noqa: ANN001
        raise RuntimeError("kaboom")

    boom.run = run
    import sys

    sys.modules["scripts.boom_mod"] = boom
    try:
        res = run_one(
            tmp_path, {"source_id": "boom", "producer_script": "scripts/boom_mod.py"}, _NullLogger()
        )
    finally:
        del sys.modules["scripts.boom_mod"]
    assert res["status"] == "ERROR"
    assert "kaboom" in res["error"]


def test_run_one_reports_rows_from_producer_dict(tmp_path):
    ok = types.ModuleType("ok_mod")
    ok.run = lambda root=None: {"rows": 7, "status": "OK"}
    import sys

    sys.modules["scripts.ok_mod"] = ok
    try:
        res = run_one(
            tmp_path, {"source_id": "ok", "producer_script": "scripts/ok_mod.py"}, _NullLogger()
        )
    finally:
        del sys.modules["scripts.ok_mod"]
    assert res["status"] == "OK"
    assert res["rows"] == 7


class _NullLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass
