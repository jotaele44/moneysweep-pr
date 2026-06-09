"""Federation conformance-fixture freshness guard (Wave E, tasks 29 + 30).

The committed federation conformance package under ``exports/conformance/v1_2/``
is the golden fixture the ``spiderweb-pr`` query-hub validates against. If the
JSONL stream files are edited but ``manifest.json`` is not regenerated, the
package silently drifts from its own manifest (wrong sha256 / record_count) and
the federation handshake can rot undetected.

These tests rebuild the manifest from the on-disk stream files via
``scripts.build_export_package.build_manifest`` and assert the committed
manifest still matches — turning any drift into a red CI check.

They also pin the **single source of truth** for the two independent contract
versions (task 30): the federation ``export_contract_version`` is owned by
``build_export_package.EXPORT_CONTRACT_VERSION`` and must agree with every place
that hardcodes the literal (the conformance manifest, the sample manifest, and
the manifest schema's ``const``). The finance-lane report version is owned
separately by ``readiness/contract_sweeper_finance_lane.py`` and the two must
never collapse into one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import build_export_package as bep

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFORMANCE_DIR = REPO_ROOT / "exports" / "conformance" / "v1_2"
CONFORMANCE_MANIFEST = CONFORMANCE_DIR / "manifest.json"


def _committed_manifest() -> dict:
    return json.loads(CONFORMANCE_MANIFEST.read_text(encoding="utf-8"))


@pytest.mark.unit
def test_conformance_dir_exists():
    assert CONFORMANCE_MANIFEST.exists(), "federation conformance manifest is missing"
    for _stream, filename, _schema in bep.STREAMS:
        assert (CONFORMANCE_DIR / filename).exists(), f"missing conformance stream {filename}"


@pytest.mark.unit
def test_conformance_files_match_committed_sha_and_counts():
    """Rebuild file records from disk; sha256 + record_count must match the manifest."""
    committed = _committed_manifest()
    rebuilt = bep.build_manifest(CONFORMANCE_DIR, mode=committed["mode"])

    committed_by_name = {f["filename"]: f for f in committed["files"]}
    rebuilt_by_name = {f["filename"]: f for f in rebuilt["files"]}
    assert set(committed_by_name) == set(rebuilt_by_name), "stream set drifted from manifest"

    for name, rebuilt_rec in rebuilt_by_name.items():
        committed_rec = committed_by_name[name]
        assert committed_rec["sha256"] == rebuilt_rec["sha256"], (
            f"{name}: sha256 drift — regenerate exports/conformance/v1_2/manifest.json"
        )
        assert committed_rec["record_count"] == rebuilt_rec["record_count"], (
            f"{name}: record_count drift — regenerate the conformance manifest"
        )
        assert committed_rec["schema_id"] == rebuilt_rec["schema_id"], f"{name}: schema_id drift"


@pytest.mark.unit
def test_conformance_package_id_is_reproducible():
    """The deterministic package_id must regenerate identically from the streams."""
    committed = _committed_manifest()
    rebuilt = bep.build_manifest(CONFORMANCE_DIR, mode=committed["mode"])
    assert committed["package_id"] == rebuilt["package_id"], (
        "package_id drift — the conformance manifest is stale relative to its streams"
    )


# --------------------------------------------------------------------------- #
# Task 30 — one importable source of truth per contract version
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_conformance_manifest_pins_federation_contract_version():
    committed = _committed_manifest()
    assert committed["export_contract_version"] == bep.EXPORT_CONTRACT_VERSION, (
        "conformance manifest version must match build_export_package.EXPORT_CONTRACT_VERSION"
    )


@pytest.mark.unit
def test_sample_manifest_pins_federation_contract_version():
    sample = json.loads(
        (REPO_ROOT / "exports" / "samples" / "manifest.sample.json").read_text(encoding="utf-8")
    )
    assert sample["export_contract_version"] == bep.EXPORT_CONTRACT_VERSION


@pytest.mark.unit
def test_manifest_schema_const_pins_federation_contract_version():
    schema = json.loads(
        (REPO_ROOT / "schemas" / "contract_sweeper_export_manifest.schema.json").read_text(
            encoding="utf-8"
        )
    )
    const = schema["properties"]["export_contract_version"]["const"]
    assert const == bep.EXPORT_CONTRACT_VERSION, (
        "manifest schema const must track build_export_package.EXPORT_CONTRACT_VERSION"
    )


@pytest.mark.unit
def test_finance_lane_version_is_independent_of_federation_version():
    """The two contract versions are separate sources of truth — never collapse them."""
    from readiness import contract_sweeper_finance_lane as finance_lane

    # They legitimately differ today (federation 1.2.0 vs finance-lane 1.0.0); the
    # point is that they are distinct constants in distinct modules. This guard
    # fails loudly only if someone wires one to import the other.
    assert finance_lane.EXPORT_CONTRACT_VERSION == "1.0.0"
    assert bep.EXPORT_CONTRACT_VERSION == "1.2.0"
    assert finance_lane.__name__ != bep.__name__
