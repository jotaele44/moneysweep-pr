from __future__ import annotations

import importlib.util
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
        self.assertTrue(endpoint_ids <= mapped)
        self.assertTrue(route_ids <= mapped)
        symbol_ids = {
            item["id"]
            for item in candidates
            if item["kind"] == "python_symbol"
            and item["path"] == "server/backend/main.py"
        }
        self.assertLessEqual(symbol_ids, mapped)

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

    def test_exception_can_cover_a_reviewed_file(self) -> None:
        manifest = self._manifest()
        manifest["exceptions"] = [
            {
                "id": "backend-file-gap",
                "reason": "GUI work is tracked separately.",
                "owner": "maintainer",
                "tracking": "ITEM-3",
                "expires_on": "2027-01-01",
                "candidate_ids": ["backend_endpoint:server/backend/main.py:GET /items"],
                "candidate_files": ["server/backend/main.py"],
            }
        ]
        candidates = parity.discover_candidates(self.root, manifest)
        covered = parity.exception_candidate_ids(manifest, candidates)
        backend_ids = {
            item["id"]
            for item in candidates
            if item["path"] == "server/backend/main.py"
        }
        self.assertLessEqual(backend_ids, covered)


if __name__ == "__main__":
    unittest.main()
