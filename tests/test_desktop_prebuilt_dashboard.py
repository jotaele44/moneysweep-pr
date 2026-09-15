"""Gates on the committed prebuilt dashboard bundle.

These run without Node.js, so they hold in every CI job rather than only in the
frontend one. The fingerprint test is the real staleness gate: it fails any change
that edits dashboard sources without regenerating the bundle.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from desktop import prebuilt

REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = REPO_ROOT / "dashboard"


@pytest.fixture(scope="module")
def manifest() -> dict:
    loaded = prebuilt.load_manifest()
    assert loaded is not None, "desktop/prebuilt-dashboard/PREBUILT_MANIFEST.json is missing"
    return loaded


def test_committed_bundle_matches_manifest_digests(manifest: dict) -> None:
    assert prebuilt.verify_bundle_bytes(manifest, prebuilt.BUNDLE_DIR) == []


def test_committed_bundle_matches_dashboard_source_fingerprint(manifest: dict) -> None:
    assert not prebuilt.is_stale(manifest, FRONTEND_DIR), (
        "The dashboard sources changed but the prebuilt bundle was not regenerated. "
        "Run: python3 scripts/build_prebuilt_dashboard.py --build"
    )


def test_bundle_serves_a_dashboard_entrypoint(manifest: dict) -> None:
    assert (prebuilt.BUNDLE_DIR / "index.html").is_file()
    assert manifest["file_count"] == len(manifest["files"]) > 0


def test_no_bundle_file_would_trip_the_size_guard() -> None:
    """size-guard.yml rejects any tracked file at or above 5 MiB, per file."""
    oversized = [
        record
        for record in prebuilt.bundle_file_records(prebuilt.BUNDLE_DIR)
        if record["bytes"] >= prebuilt.SIZE_GUARD_MAX_BYTES
    ]
    assert oversized == []


def test_bundle_did_not_quietly_take_a_size_guard_exemption() -> None:
    allowlist = REPO_ROOT / ".github/size-guard-allowlist.txt"
    if not allowlist.is_file():
        return
    entries = allowlist.read_text(encoding="utf-8").splitlines()
    assert not [line for line in entries if "prebuilt-dashboard" in line]


def test_bundle_is_actually_tracked_and_not_gitignored() -> None:
    """Catches a bundle path containing a `dist`/`build` component, which .gitignore eats."""
    probe = prebuilt.BUNDLE_DIR / "index.html"
    result = subprocess.run(
        ["git", "check-ignore", "-q", str(probe)], cwd=REPO_ROOT, capture_output=True
    )
    assert result.returncode != 0, f"{probe} is gitignored and would never be committed"


def _stage_bundle(tmp_path: Path) -> tuple[Path, Path]:
    bundle = tmp_path / "bundle"
    shutil.copytree(prebuilt.BUNDLE_DIR, bundle)
    manifest_path = tmp_path / "PREBUILT_MANIFEST.json"
    shutil.copy(prebuilt.MANIFEST_PATH, manifest_path)
    return bundle, manifest_path


def test_install_refuses_a_corrupted_bundle(tmp_path: Path) -> None:
    bundle, manifest_path = _stage_bundle(tmp_path)
    (bundle / "index.html").write_text("<!-- tampered -->", encoding="utf-8")

    with pytest.raises(SystemExit, match="corrupted"):
        prebuilt.install_prebuilt_dashboard(
            tmp_path / "dist", bundle_dir=bundle, manifest_path=manifest_path
        )


def test_install_returns_false_when_no_bundle_is_present(tmp_path: Path) -> None:
    assert not prebuilt.install_prebuilt_dashboard(
        tmp_path / "dist",
        bundle_dir=tmp_path / "absent",
        manifest_path=tmp_path / "absent.json",
    )


def test_stale_bundle_is_used_when_no_source_build_is_possible(tmp_path: Path) -> None:
    """Failing an end user over maintainer staleness would recreate the dead end."""
    bundle, manifest_path = _stage_bundle(tmp_path)
    stale = json.loads(manifest_path.read_text(encoding="utf-8"))
    stale["source_fingerprint"] = "0" * 64
    manifest_path.write_text(json.dumps(stale), encoding="utf-8")
    dist = tmp_path / "dist"

    installed = prebuilt.install_prebuilt_dashboard(
        dist, bundle_dir=bundle, manifest_path=manifest_path, source_build_available=False
    )

    assert installed
    assert (dist / "index.html").is_file()


def test_stale_bundle_defers_to_a_real_build_when_node_is_available(tmp_path: Path) -> None:
    bundle, manifest_path = _stage_bundle(tmp_path)
    stale = json.loads(manifest_path.read_text(encoding="utf-8"))
    stale["source_fingerprint"] = "0" * 64
    manifest_path.write_text(json.dumps(stale), encoding="utf-8")

    assert not prebuilt.install_prebuilt_dashboard(
        tmp_path / "dist",
        bundle_dir=bundle,
        manifest_path=manifest_path,
        source_build_available=True,
    )


def test_fingerprint_ignores_test_only_sources(tmp_path: Path) -> None:
    frontend = tmp_path / "dashboard"
    (frontend / "src").mkdir(parents=True)
    (frontend / "package.json").write_text("{}", encoding="utf-8")
    (frontend / "src" / "App.jsx").write_text("export default 1", encoding="utf-8")
    before = prebuilt.source_fingerprint(frontend)

    (frontend / "src" / "App.test.jsx").write_text("test stuff", encoding="utf-8")

    assert prebuilt.source_fingerprint(frontend) == before


def test_fingerprint_changes_when_a_real_source_changes(tmp_path: Path) -> None:
    frontend = tmp_path / "dashboard"
    (frontend / "src").mkdir(parents=True)
    (frontend / "src" / "App.jsx").write_text("export default 1", encoding="utf-8")
    before = prebuilt.source_fingerprint(frontend)

    (frontend / "src" / "App.jsx").write_text("export default 2", encoding="utf-8")

    assert prebuilt.source_fingerprint(frontend) != before


def test_bootstrap_is_classified_as_an_internal_capability() -> None:
    extension = json.loads(
        (
            REPO_ROOT / ".federation/gui-capabilities.extensions/desktop-offline-bootstrap.json"
        ).read_text(encoding="utf-8")
    )
    capability = extension["capabilities"][0]
    assert capability["classification"] == "internal"
    assert capability["rationale"].strip()
    assert (
        "python_symbol:desktop/prebuilt.py:install_prebuilt_dashboard"
        in (capability["candidate_ids"])
    )
