from __future__ import annotations

from pathlib import Path

from scripts import run_automatable_sources_scoped as scoped


def test_credential_available_treats_missing_or_blank_as_unavailable(monkeypatch) -> None:
    monkeypatch.delenv("EIA_API_KEY", raising=False)
    assert scoped._credential_available("EIA_API_KEY") is False
    monkeypatch.setenv("EIA_API_KEY", "   ")
    assert scoped._credential_available("EIA_API_KEY") is False
    monkeypatch.setenv("EIA_API_KEY", "fixture-eia")
    assert scoped._credential_available("EIA_API_KEY") is True
    assert scoped._credential_available(None) is True


def test_missing_declared_api_key_blocks_before_run_one(monkeypatch, tmp_path: Path) -> None:
    sources = [
        {
            "source_id": "eia_power_sector",
            "family": "federal",
            "authentication": "api_key:EIA_API_KEY",
            "producer_script": "scripts/download_eia.py",
        }
    ]

    monkeypatch.setattr(scoped, "load_source_registry", lambda root: {"sources": sources})
    monkeypatch.setattr(scoped, "_select_sources", lambda *args, **kwargs: sources)
    monkeypatch.delenv("EIA_API_KEY", raising=False)

    called = {"run_one": False}

    def forbidden_run_one(*args, **kwargs):
        called["run_one"] = True
        raise AssertionError("producer execution must not occur when its API key is missing")

    monkeypatch.setattr(scoped.base, "run_one", forbidden_run_one)
    monkeypatch.setattr(scoped.base, "_write_summary", lambda *args, **kwargs: None)

    result = scoped.run(root=tmp_path, require_egress=False)

    assert called["run_one"] is False
    assert result["ran"][0]["status"] == "MISSING_API_KEY"
    assert result["missing_api_key_count"] == 1
    assert result["ok_count"] == 0


def test_present_declared_api_key_allows_run_one(monkeypatch, tmp_path: Path) -> None:
    sources = [
        {
            "source_id": "eia_power_sector",
            "family": "federal",
            "authentication": "api_key:EIA_API_KEY",
            "producer_script": "scripts/download_eia.py",
        }
    ]

    monkeypatch.setattr(scoped, "load_source_registry", lambda root: {"sources": sources})
    monkeypatch.setattr(scoped, "_select_sources", lambda *args, **kwargs: sources)
    monkeypatch.setenv("EIA_API_KEY", "fixture-eia")

    seen = {}

    def fake_run_one(root, src, logger):
        seen["key"] = __import__("os").environ.get("EIA_API_KEY")
        return {
            "source": src["source_id"],
            "producer": src["producer_script"],
            "status": "OK",
            "rows": 1,
            "error": "",
        }

    monkeypatch.setattr(scoped.base, "run_one", fake_run_one)
    monkeypatch.setattr(scoped.base, "_write_summary", lambda *args, **kwargs: None)

    result = scoped.run(root=tmp_path, require_egress=False)

    assert seen["key"] == "fixture-eia"
    assert result["ran"][0]["status"] == "OK"
    assert result["missing_api_key_count"] == 0
    assert result["ok_count"] == 1
