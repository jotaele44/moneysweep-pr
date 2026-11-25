"""Regression tests for scripts/check_gui_parity.py.

Rendered from thehub-pr/federation-templates/gui/test_gui_parity.py.
Do not hand-edit - template-drift.yml fails the build if you do. Change the
template and re-render.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

# fmt: off

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_gui_parity.py"
SPEC = importlib.util.spec_from_file_location("check_gui_parity", SCRIPT)
assert SPEC and SPEC.loader
parity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(parity)


class GuiParityContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self._write(
            "server/backend/main.py",
            """
from fastapi import FastAPI
app = FastAPI()

@app.get("/items")
def list_items():
    return []
""".strip()
            + "\n",
        )
        self._write(
            "frontend/src/App.jsx",
            """
import { Route, Routes } from "react-router-dom";
import Items from "./pages/Items";
export default function App() {
  return <Routes><Route path="/items" element={<Items />} /></Routes>;
}
""".strip()
            + "\n",
        )
        self._write(
            "frontend/src/Header.jsx",
            'export default () => <a href="/items">Items</a>;\n',
        )
        self._write(
            "frontend/src/pages/Items.jsx",
            """
export default function Items() {
  return <button onClick={() => fetch("/items")}>Refresh</button>;
}
""".strip()
            + "\n",
        )
        self._write("frontend/tests/gui-parity.spec.mjs", "// browser smoke\n")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _manifest(self) -> dict:
        return {
            "schema_version": parity.MANIFEST_SCHEMA,
            "repository": "example/repo",
            "discovery": {
                "backend_roots": ["server/backend"],
                "production_roots": [],
                "analysis_roots": [],
                "frontend_roots": ["frontend/src"],
                "frontend_capability_roots": ["frontend/src/pages"],
                "frontend_api_roots": [],
                "route_files": ["frontend/src/App.jsx"],
                "navigation_files": ["frontend/src/Header.jsx"],
                "exclude": [],
            },
            "capabilities": [
                {
                    "id": "items",
                    "classification": "user",
                    "status": "active",
                    "requires_terminal": False,
                    "backend": {
                        "files": ["server/backend/main.py"],
                        "endpoints": ["GET /items"],
                    },
                    "frontend": {
                        "routes": ["/items"],
                        "e2e_routes": ["/items"],
                        "components": ["frontend/src/pages/Items.jsx"],
                        "discoverability": ["frontend/src/Header.jsx"],
                    },
                    "tests": {
                        "e2e": ["frontend/tests/gui-parity.spec.mjs"],
                    },
                }
            ],
            "exceptions": [],
        }

    def test_complete_capability_is_bidirectionally_valid(self) -> None:
        manifest = self._manifest()
        candidates = parity.discover_candidates(self.root, manifest)
        issues = parity.validate_manifest(self.root, manifest, candidates)
        self.assertEqual([], issues)
        mapped = parity.mapped_candidate_ids(manifest, candidates)
        endpoint_ids = {
            item["id"]
            for item in candidates
            if item["kind"] == "backend_endpoint"
        }
        route_ids = {
            item["id"] for item in candidates if item["kind"] == "gui_route"
        }
        self.assertLessEqual(endpoint_ids, mapped)
        self.assertLessEqual(route_ids, mapped)
        # A file bound without a symbol list binds every public symbol in it.
        symbol_ids = {
            item["id"]
            for item in candidates
            if item["kind"] == "python_symbol"
            and item["path"] == "server/backend/main.py"
        }
        self.assertTrue(symbol_ids)
        self.assertLessEqual(symbol_ids, mapped)

    def test_listing_symbols_narrows_the_file_binding(self) -> None:
        manifest = self._manifest()
        manifest["capabilities"][0]["backend"]["symbols"] = [
            "server/backend/main.py:something_else"
        ]
        candidates = parity.discover_candidates(self.root, manifest)
        mapped = parity.mapped_candidate_ids(manifest, candidates)
        self.assertNotIn("python_symbol:server/backend/main.py:list_items", mapped)

    def test_empty_router_path_is_inventory_root_endpoint(self) -> None:
        self._write(
            "server/backend/main.py",
            """
from fastapi import APIRouter
router = APIRouter(prefix="/api/items")

@router.get("")
def list_items():
    return []
""".strip()
            + "\n",
        )
        manifest = self._manifest()
        manifest["capabilities"][0]["backend"]["endpoints"] = ["GET /"]

        candidates = parity.discover_candidates(self.root, manifest)
        issues = parity.validate_manifest(self.root, manifest, candidates)

        self.assertEqual([], issues)
        self.assertIn(
            "GET /",
            {
                item["detail"]
                for item in candidates
                if item["kind"] == "backend_endpoint"
            },
        )

    def test_backend_without_gui_is_rejected(self) -> None:
        manifest = self._manifest()
        manifest["capabilities"][0]["frontend"] = {}
        candidates = parity.discover_candidates(self.root, manifest)
        issues = parity.validate_manifest(self.root, manifest, candidates)
        codes = {item["code"] for item in issues}
        self.assertIn("BACKEND_NOT_GUI_SURFACED", codes)
        self.assertIn("GUI_PATH_NOT_E2E_TESTED", codes)

    def test_ratchet_rejects_a_new_unclassified_endpoint(self) -> None:
        manifest = self._manifest()
        before = parity.discover_candidates(self.root, manifest)
        baseline = parity.build_baseline(manifest, before)
        with (self.root / "server/backend/main.py").open("a", encoding="utf-8") as handle:
            handle.write(
                '\n@app.post("/items/run")\ndef run_items():\n    return {"ok": True}\n'
            )
        after = parity.discover_candidates(self.root, manifest)
        issues = parity.validate_manifest(self.root, manifest, after)
        report, passed = parity.evaluate(
            manifest, baseline, after, issues, strict=False
        )
        self.assertFalse(passed)
        # The new endpoint is unpaired; its handler is covered by the file
        # binding, so exactly one gap is new.
        self.assertEqual(1, report["summary"]["new_gaps"])
        self.assertTrue(
            all(
                item["signal"] == "BACKEND_NOT_GUI_SURFACED"
                for item in report["new_findings"]
            )
        )

    def test_expired_staged_capability_and_exception_are_rejected(self) -> None:
        manifest = self._manifest()
        manifest["capabilities"][0].update(
            {
                "status": "staged",
                "feature_flag": "items",
                "tracking": "ITEM-1",
                "expires_on": "2025-01-01",
            }
        )
        manifest["exceptions"] = [
            {
                "id": "expired",
                "reason": "temporary",
                "owner": "maintainer",
                "tracking": "ITEM-2",
                "expires_on": "2025-01-01",
                "candidate_ids": ["example"],
            }
        ]
        candidates = parity.discover_candidates(self.root, manifest)
        issues = parity.validate_manifest(
            self.root, manifest, candidates, today=date(2026, 1, 1)
        )
        codes = [item["code"] for item in issues]
        self.assertEqual(2, codes.count("EXPIRED_PARITY_EXCEPTION"))

    def test_discovery_uses_canonical_repo_root(self) -> None:
        alias_root = self.root.parent / (self.root.name + "-alias")
        try:
            alias_root.symlink_to(self.root, target_is_directory=True)
        except OSError:
            self.skipTest("directory symlinks are unavailable")
        self.addCleanup(alias_root.unlink)
        files = parity._iter_files(alias_root, ["server/backend"], {".py"}, [])
        self.assertEqual([self.root.resolve() / "server/backend/main.py"], files)

    def test_exception_can_cover_a_reviewed_file(self) -> None:
        manifest = self._manifest()
        manifest["exceptions"] = [
            {
                "id": "backend-file-gap",
                "reason": "GUI work is tracked separately.",
                "owner": "maintainer",
                "tracking": "ITEM-3",
                "expires_on": "2027-01-01",
                "candidate_files": ["server/backend/main.py"],
            }
        ]
        candidates = parity.discover_candidates(self.root, manifest)
        issues = parity.validate_manifest(
            self.root, manifest, candidates, today=date(2026, 12, 1)
        )
        self.assertEqual([], issues)
        covered = parity.exception_candidate_ids(manifest, candidates)
        backend_ids = {
            item["id"]
            for item in candidates
            if item["path"] == "server/backend/main.py"
        }
        self.assertLessEqual(backend_ids, covered)

    def test_exception_must_name_what_it_covers(self) -> None:
        manifest = self._manifest()
        manifest["exceptions"] = [
            {
                "id": "covers-nothing",
                "reason": "temporary",
                "owner": "maintainer",
                "tracking": "ITEM-4",
                "expires_on": "2027-01-01",
            }
        ]
        candidates = parity.discover_candidates(self.root, manifest)
        issues = parity.validate_manifest(
            self.root, manifest, candidates, today=date(2026, 12, 1)
        )
        self.assertEqual(["INVALID_EXCEPTION"], [item["code"] for item in issues])

    def test_baseline_does_not_pin_the_manifest(self) -> None:
        manifest = self._manifest()
        baseline = parity.build_baseline(
            manifest, parity.discover_candidates(self.root, manifest)
        )
        self.assertNotIn("manifest_sha256", baseline)

    def test_missing_navigation_file_is_rejected(self) -> None:
        manifest = self._manifest()
        manifest["discovery"]["navigation_files"] = ["frontend/src/Gone.jsx"]
        candidates = parity.discover_candidates(self.root, manifest)
        issues = parity.validate_manifest(self.root, manifest, candidates)
        self.assertEqual(
            ["MISSING_NAVIGATION_FILE"], [item["code"] for item in issues]
        )

    def test_declared_e2e_spec_must_be_collected(self) -> None:
        self._write(
            "frontend/gui-parity.playwright.config.mjs",
            'export default { testMatch: ["other.spec.mjs"] };\n',
        )
        manifest = self._manifest()
        manifest["discovery"]["e2e_config"] = [
            "frontend/gui-parity.playwright.config.mjs"
        ]
        candidates = parity.discover_candidates(self.root, manifest)
        issues = parity.validate_manifest(self.root, manifest, candidates)
        self.assertEqual(
            ["E2E_SPEC_NOT_COLLECTED"], [item["code"] for item in issues]
        )

        self._write(
            "frontend/gui-parity.playwright.config.mjs",
            'export default { testMatch: ["gui-parity.spec.mjs"] };\n',
        )
        self.assertEqual(
            [], parity.validate_manifest(self.root, manifest, candidates)
        )

        manifest["discovery"]["e2e_config"] = "frontend/missing.config.mjs"
        codes = {
            item["code"]
            for item in parity.validate_manifest(self.root, manifest, candidates)
        }
        self.assertIn("MISSING_E2E_CONFIG", codes)

    def test_core_capability_keeps_its_classification(self) -> None:
        manifest = self._manifest()
        manifest["capabilities"][0]["id"] = "service-health"
        candidates = parity.discover_candidates(self.root, manifest)
        issues = parity.validate_manifest(self.root, manifest, candidates)
        self.assertEqual(
            ["CORE_CAPABILITY_MISMATCH"], [item["code"] for item in issues]
        )

    def test_expiry_warnings_flag_imminent_and_distant_dates(self) -> None:
        manifest = self._manifest()
        base = {"reason": "r", "owner": "o", "tracking": "T", "candidate_ids": ["x"]}
        manifest["exceptions"] = [
            {**base, "id": "soon", "expires_on": "2026-01-10"},
            {**base, "id": "fine", "expires_on": "2026-02-15"},
            {**base, "id": "far", "expires_on": "2027-01-01"},
            {**base, "id": "gone", "expires_on": "2025-12-01"},
        ]
        warnings = parity.expiry_warnings(manifest, today=date(2026, 1, 1))
        self.assertEqual(
            ["PARITY_EXPIRY_IMMINENT", "PARITY_EXPIRY_TOO_FAR"],
            [item["code"] for item in warnings],
        )
        self.assertIn("soon", warnings[0]["message"])
        self.assertIn("far", warnings[1]["message"])


class GuiParityExtensionTests(unittest.TestCase):
    """Repo-specific expansion: fragments append, and only append."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.manifest_path = self.root / ".federation" / "gui-capabilities.json"
        self.base = {
            "schema_version": parity.MANIFEST_SCHEMA,
            "repository": "example/repo",
            "discovery": {},
            "capabilities": [
                {"id": "base", "classification": "internal", "status": "active"}
            ],
            "exceptions": [],
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _fragment(self, stem: str, body: dict) -> None:
        directory = parity.extensions_dir(self.manifest_path)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{stem}.json").write_text(json.dumps(body), encoding="utf-8")

    def _capability(self, capability_id: str) -> dict:
        return {"id": capability_id, "classification": "internal", "status": "active"}

    def test_extensions_directory_sits_beside_the_manifest(self) -> None:
        self.assertEqual(
            self.root / ".federation" / "gui-capabilities.extensions",
            parity.extensions_dir(self.manifest_path),
        )

    def test_no_extensions_directory_is_a_no_op(self) -> None:
        merged, names, issues = parity.merge_extensions(self.base, self.manifest_path)
        self.assertEqual(self.base, merged)
        self.assertEqual([], names)
        self.assertEqual([], issues)

    def test_fragments_append_in_filename_order(self) -> None:
        self._fragment(
            "b-second",
            {"extension_id": "b-second", "capabilities": [self._capability("b")]},
        )
        self._fragment(
            "a-first",
            {"extension_id": "a-first", "capabilities": [self._capability("a")]},
        )
        merged, names, issues = parity.merge_extensions(self.base, self.manifest_path)
        self.assertEqual([], issues)
        self.assertEqual(["a-first.json", "b-second.json"], names)
        self.assertEqual(
            ["base", "a", "b"], [item["id"] for item in merged["capabilities"]]
        )
        # The base manifest object is left untouched.
        self.assertEqual(1, len(self.base["capabilities"]))

    def test_fragment_cannot_change_discovery_or_policy(self) -> None:
        self._fragment(
            "sneaky",
            {
                "extension_id": "sneaky",
                "discovery": {"exclude": ["**"]},
                "capabilities": [self._capability("extra")],
            },
        )
        merged, names, issues = parity.merge_extensions(self.base, self.manifest_path)
        self.assertEqual(
            ["INVALID_EXTENSION_FRAGMENT"], [item["code"] for item in issues]
        )
        self.assertEqual([], names)
        self.assertEqual({}, merged["discovery"])
        self.assertEqual(["base"], [item["id"] for item in merged["capabilities"]])

    def test_fragment_must_be_named_after_its_extension_id(self) -> None:
        self._fragment("named", {"capabilities": [self._capability("extra")]})
        _, names, issues = parity.merge_extensions(self.base, self.manifest_path)
        self.assertEqual(
            ["INVALID_EXTENSION_FRAGMENT"], [item["code"] for item in issues]
        )
        self.assertEqual([], names)

    def test_fragment_cannot_redefine_a_base_entry(self) -> None:
        self._fragment(
            "override",
            {"extension_id": "override", "capabilities": [self._capability("base")]},
        )
        merged, _, issues = parity.merge_extensions(self.base, self.manifest_path)
        self.assertEqual(
            ["EXTENSION_REDEFINES_BASE"], [item["code"] for item in issues]
        )
        self.assertEqual(1, len(merged["capabilities"]))

    def test_duplicate_ids_across_fragments_are_rejected(self) -> None:
        for stem in ("one", "two"):
            self._fragment(
                stem,
                {"extension_id": stem, "capabilities": [self._capability("shared")]},
            )
        merged, _, issues = parity.merge_extensions(self.base, self.manifest_path)
        self.assertEqual([], issues)
        codes = [
            item["code"] for item in parity.validate_manifest(self.root, merged, [])
        ]
        self.assertIn("DUPLICATE_CAPABILITY_ID", codes)

    def test_unreadable_fragment_is_reported_not_fatal(self) -> None:
        directory = parity.extensions_dir(self.manifest_path)
        directory.mkdir(parents=True)
        (directory / "broken.json").write_text("{", encoding="utf-8")
        self._fragment(
            "good", {"extension_id": "good", "capabilities": [self._capability("g")]}
        )
        merged, names, issues = parity.merge_extensions(self.base, self.manifest_path)
        self.assertEqual(["good.json"], names)
        self.assertEqual(
            ["INVALID_EXTENSION_FRAGMENT"], [item["code"] for item in issues]
        )
        self.assertEqual(
            ["base", "g"], [item["id"] for item in merged["capabilities"]]
        )

    def test_cli_merges_by_default_and_can_emit_the_merged_manifest(self) -> None:
        self.manifest_path.parent.mkdir(parents=True)
        base = {**self.base, "capabilities": []}
        self.manifest_path.write_text(json.dumps(base), encoding="utf-8")
        self._fragment(
            "extra",
            {
                "extension_id": "extra",
                "capabilities": [
                    {
                        "id": "extra",
                        "classification": "internal",
                        "status": "active",
                        "requires_terminal": False,
                        "rationale": "infrastructure",
                    }
                ],
            },
        )
        root = ["--repo-root", str(self.root)]
        self.assertEqual(0, parity.main([*root, "--write-baseline"]))
        self.assertEqual(
            0,
            parity.main(
                [*root, "--emit-merged", "out/merged.json", "--report", "out/r.json"]
            ),
        )
        merged = json.loads((self.root / "out/merged.json").read_text())
        self.assertEqual(["extra"], [item["id"] for item in merged["capabilities"]])
        report = json.loads((self.root / "out/r.json").read_text())
        self.assertEqual(["extra.json"], report["extensions"])

        self.assertEqual(
            0,
            parity.main(
                [*root, "--no-extensions", "--emit-merged", "out/base.json"]
            ),
        )
        base_only = json.loads((self.root / "out/base.json").read_text())
        self.assertEqual([], base_only["capabilities"])


if __name__ == "__main__":
    unittest.main()
