"""Offline denylist and original-PDF byte acceptance regression."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

S = Path(__file__).parents[1] / "scripts" / "acquire_pr_education_primary_audits.py"
spec = importlib.util.spec_from_file_location("acquire_pdf", S)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class PDFProbeTests(unittest.TestCase):
    def test_only_three_sources(self):
        self.assertEqual(set(m.SOURCES), {"prde_2020", "upr_2023", "upr_2024"})

    def test_all_origins_are_pr_treasury(self):
        for u in m.SOURCES.values():
            self.assertTrue(u.startswith("https://hacienda.pr.gov/sites/default/files/"))

    def test_http_not_allowed(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError, "NON_GOVERNMENT_SOURCE_DENIED"):
                m.fetch_pdf("http://hacienda.pr.gov/file.pdf", Path(d)/"file.pdf")

    def test_lookalike_domain_denied(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError, "NON_GOVERNMENT_SOURCE_DENIED"):
                m.fetch_pdf("https://hacienda.pr.gov.evil.test/file.pdf", Path(d)/"file.pdf")

    def test_missing_source_fails_closed_and_writes_receipt(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(m, "fetch_pdf", side_effect=OSError("offline")):
                code = m.run(Path(d))
            self.assertEqual(code, 2)
            self.assertIn("WITHHELD", (Path(d)/"source_receipt.json").read_text())

    def test_sha256_exact(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"bytes"
            path.write_bytes(b"source bytes")
            self.assertEqual(m.sha256(path), "4097ddc77448e120201892f65e8ad0f49cd84e99b5ab30d81b44a15e36a9bdda")


if __name__ == "__main__":
    unittest.main()
