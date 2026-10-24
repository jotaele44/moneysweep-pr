"""Offline adversarial tests. No network, no real source substitution."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

M = Path(__file__).parents[1] / "scripts" / "acquire_sam_public_snapshot.py"
spec = importlib.util.spec_from_file_location("sam_probe", M)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
HEADER = "Program Number,Program Title,Types of Assistance (060)\n"
ROWS = "10.123,Federal Test Grant,GRANT\n10.124,Other Test,TRAINING\n"

class ProbeTests(unittest.TestCase):
    def parse(self, data):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/"data.csv"
            p.write_bytes(data.encode('cp1252'))
            return probe.parse_snapshot(p)

    def test_conservation(self):
        r = self.parse(HEADER + ROWS)
        self.assertEqual(r['rows'], r['unique_program_numbers'])
        self.assertEqual(r['rows'], r['financial_listing_rows'] + r['nonfinancial_listing_rows'])
    def test_financial_nonfinancial(self):
        r=self.parse(HEADER+ROWS)
        self.assertEqual(r['financial_listing_rows'],1)
        self.assertEqual(r['nonfinancial_listing_rows'],1)
    def test_exact_alphanumeric(self):
        r=self.parse(HEADER + "10.ABC,Test,GRANT\n10.abc,Test,GRANT\n")
        self.assertEqual(r['rows'],2)
    def test_duplicate_rejected(self):
        with self.assertRaisesRegex(ValueError,'DUPLICATE_PROGRAM_NUMBER'):
            self.parse(HEADER + "10.123,First,GRANT\n10.123,Second,LOAN\n")
    def test_missing_id_rejected(self):
        with self.assertRaisesRegex(ValueError,'BLANK_PROGRAM_NUMBER'):
            self.parse(HEADER + ",Test,GRANT\n")
    def test_missing_title_rejected(self):
        with self.assertRaisesRegex(ValueError,'BLANK_PROGRAM_TITLE'):
            self.parse(HEADER + "10.123,,GRANT\n")
    def test_preamble(self):
        self.assertEqual(self.parse("Vendor export\n"+HEADER+ROWS)['rows'],2)
    def test_missing_header(self):
        with self.assertRaisesRegex(ValueError,'SAM_HEADER'):
            self.parse("Broken file\n")
    def test_duplicate_header(self):
        with self.assertRaisesRegex(ValueError,'SAM_HEADER_INVALID'):
            self.parse('Program Number,Program Title,Types of Assistance (060),Program Number\n10.123,A,GRANT,EXTRA\n')
    def test_overflow(self):
        with self.assertRaisesRegex(ValueError,'CSV_COLUMN_OVERFLOW'):
            self.parse(HEADER + "10.123,A,GRANT,OVERFLOW\n")
    def test_empty_dataset(self):
        with self.assertRaisesRegex(ValueError,'EMPTY_PROGRAM_SOURCE'):
            self.parse(HEADER)
    def test_not_promoted(self):
        self.assertTrue(self.parse(HEADER+ROWS)['no_canonical_identity_promotion'])

if __name__ == '__main__': unittest.main()
