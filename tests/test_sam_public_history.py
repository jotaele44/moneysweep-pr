"""History reconciliation denial tests with local synthetic records only."""
import importlib.util
import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
P=Path(__file__).parents[1]/'scripts/reconcile_sam_public_history.py'
spec=importlib.util.spec_from_file_location('sam_compare',P)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
HEADER='Program Number,Program Title\n'

def digest(x):return hashlib.sha256(x).hexdigest()

class TestReconcile(unittest.TestCase):
  def fixture(self,root):
    old=(HEADER+'10.001,A\n10.002,B\n').encode()
    cur=(HEADER+'10.002,B\n10.003,C\n').encode()
    past=root/'old.csv.gz';past.write_bytes(gzip.compress(old))
    now=root/'new.csv';now.write_bytes(cur)
    rm={'snapshot_date':'2026-08-27','source':{'compression':'gzip','artifact_bytes':past.stat().st_size,'artifact_sha256':mod.sha(past),'bytes':len(old),'sha256':digest(old)},'denominator':{'assistance_listing_rows':2}}
    manifest=root/'metadata.json';manifest.write_text(json.dumps(rm))
    receipt=root/'receipt.json';receipt.write_text(json.dumps({'state':'SOURCE_BYTES_ACQUIRED_BOUNDED_PARSE_PASS','source_sha256':digest(cur),'source_size_bytes':len(cur),'parse':{'rows':2}}))
    return now,receipt,past,manifest
  def test_exact_membership(self):
    with tempfile.TemporaryDirectory() as d:
      p=Path(d);a=self.fixture(p)
      r=mod.reconcile(*a,p/'out')
      self.assertEqual((r['intersection_count'],r['historical_only_count'],r['current_only_count'],r['union_count'],r['symmetric_difference_count']),(1,1,1,3,2))
      self.assertEqual(r['historical_only_ids'],['10.001'])
      self.assertEqual(r['current_only_ids'],['10.003'])
      self.assertFalse(r['canonical_promotion_allowed'])
  def test_tamper_archive_denied(self):
    with tempfile.TemporaryDirectory() as d:
      p=Path(d);now,receipt,arc,meta=self.fixture(p)
      arc.write_bytes(arc.read_bytes()+b'x')
      with self.assertRaisesRegex(ValueError,'HISTORICAL_ARCHIVE_HASH_MISMATCH'):mod.reconcile(now,receipt,arc,meta,p/'out')
  def test_tamper_current_denied(self):
    with tempfile.TemporaryDirectory() as d:
      p=Path(d);now,receipt,arc,meta=self.fixture(p)
      now.write_bytes(now.read_bytes()+b'x')
      with self.assertRaisesRegex(ValueError,'CURRENT_RAW_HASH_MISMATCH'):mod.reconcile(now,receipt,arc,meta,p/'out')
  def test_duplicate_old_denied(self):
    with tempfile.TemporaryDirectory() as d:
      p=Path(d);now,receipt,arc,meta=self.fixture(p)
      old=(HEADER+'10.001,A\n10.001,B\n').encode();arc.write_bytes(gzip.compress(old))
      j=json.loads(meta.read_text());j['source'].update(artifact_bytes=arc.stat().st_size,artifact_sha256=mod.sha(arc),bytes=len(old),sha256=digest(old));meta.write_text(json.dumps(j))
      with self.assertRaisesRegex(ValueError,'INVALID_SOURCE_MEMBERSHIP'):mod.reconcile(now,receipt,arc,meta,p/'out')
  def test_source_scope_remains_open(self):
    with tempfile.TemporaryDirectory() as d:
      p=Path(d);r=mod.reconcile(*self.fixture(p),p/'out')
      self.assertFalse(r['scope_closed'])
      self.assertFalse(r['pr_nexus_certified'])

if __name__=='__main__':unittest.main()
