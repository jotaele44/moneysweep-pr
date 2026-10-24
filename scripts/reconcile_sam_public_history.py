#!/usr/bin/env python3
"""Exact source membership reconciliation; never promotes IDs to PR programs."""
from __future__ import annotations
import csv
import gzip
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT/'data/reference/AssistanceListings_DataGov_c32925ccdefe425d.csv.gz'
METADATA = ROOT/'data/reference/federal_financial_program_denominator_20260827.json'


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def membership(path: Path) -> dict[str,str]:
    out={}
    with path.open('r',encoding='cp1252',newline='') as stream:
        reader=csv.DictReader(stream)
        if not {'Program Number','Program Title'}.issubset(reader.fieldnames or []):
            raise ValueError('SOURCE_SCHEMA_INVALID')
        for idx,row in enumerate(reader,1):
            number=(row.get('Program Number') or '').strip()
            title=(row.get('Program Title') or '').strip()
            if not number or not title or number in out or None in row:
                raise ValueError(f'INVALID_SOURCE_MEMBERSHIP_AT_ROW_{idx}')
            out[number]=title
    if not out:
        raise ValueError('ZERO_ROW_SOURCE')
    return out


def reconcile(current_csv: Path, current_receipt: Path, archive: Path, metadata: Path, outdir: Path) -> dict:
    record=json.loads(metadata.read_text())
    rs=json.loads(current_receipt.read_text())
    historic=record['source']
    if historic['compression']!='gzip':
        raise ValueError('HISTORICAL_COMPRESSION_UNEXPECTED')
    if archive.stat().st_size!=historic['artifact_bytes'] or sha(archive)!=historic['artifact_sha256']:
        raise ValueError('HISTORICAL_ARCHIVE_HASH_MISMATCH')
    if current_csv.stat().st_size!=rs['source_size_bytes'] or sha(current_csv)!=rs['source_sha256']:
        raise ValueError('CURRENT_RAW_HASH_MISMATCH')
    if rs['state']!='SOURCE_BYTES_ACQUIRED_BOUNDED_PARSE_PASS':
        raise ValueError('CURRENT_ACQUISITION_NOT_VERIFIED')
    with tempfile.TemporaryDirectory() as d:
        uncompressed=Path(d)/'august_27.csv'
        with gzip.open(archive,'rb') as f,uncompressed.open('wb') as w:
            shutil.copyfileobj(f,w)
        if uncompressed.stat().st_size!=historic['bytes'] or sha(uncompressed)!=historic['sha256']:
            raise ValueError('HISTORICAL_RAW_HASH_MISMATCH')
        old=membership(uncompressed)
    current=membership(current_csv)
    den=record['denominator']
    if len(old)!=den['assistance_listing_rows']:
        raise ValueError('HISTORICAL_DENOMINATOR_MISMATCH')
    if len(current)!=rs['parse']['rows']:
        raise ValueError('CURRENT_DENOMINATOR_MISMATCH')
    old_set=set(old);cur_set=set(current)
    added=sorted(cur_set-old_set);removed=sorted(old_set-cur_set)
    shared=sorted(old_set & cur_set)
    title_changes=[{'program_number':x,'old_title':old[x],'current_title':current[x]} for x in shared if old[x]!=current[x]]
    assert len(old_set | cur_set)==len(shared)+len(added)+len(removed)
    assert len(old_set ^ cur_set)==len(added)+len(removed)
    outdir.mkdir(parents=True,exist_ok=True)
    target=outdir/archive.name
    shutil.copyfile(archive,target)
    result={
      'schema_version':'pr_registry_exact_sam_membership_delta_v1',
      'scope':'GSA_SAM_PUBLIC_CURRENT_ONLY_NOT_ALL_ACTIVE_INACTIVE',
      'historical_snapshot_date':record['snapshot_date'],
      'historic_archive_sha256':sha(archive),
      'historic_raw_sha256':historic['sha256'],
      'current_raw_sha256':sha(current_csv),
      'historic_listing_count':len(old),
      'current_listing_count':len(current),
      'intersection_count':len(shared),
      'historical_only_count':len(removed),
      'current_only_count':len(added),
      'union_count':len(old_set | cur_set),
      'symmetric_difference_count':len(old_set ^ cur_set),
      'historical_only_ids':removed,
      'current_only_ids':added,
      'shared_id_title_changes':title_changes,
      'historical_membership_sha256':hashlib.sha256(('\n'.join(sorted(old))+'\n').encode()).hexdigest(),
      'current_membership_sha256':hashlib.sha256(('\n'.join(sorted(current))+'\n').encode()).hexdigest(),
      'scope_closed':False,
      'pr_nexus_certified':False,
      'canonical_promotion_allowed':False,
      'certification':'WITHHELD',
    }
    (outdir/'sam_membership_delta.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    return result


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--current',type=Path,default=Path('outputs/sam_source_probe/AssistanceListings_DataGov_PUBLIC_CURRENT.csv'))
    parser.add_argument('--receipt',type=Path,default=Path('outputs/sam_source_probe/source_receipt.json'))
    parser.add_argument('--historic',type=Path,default=ARCHIVE)
    parser.add_argument('--manifest',type=Path,default=METADATA)
    parser.add_argument('--outdir',type=Path,default=Path('outputs/sam_source_probe'))
    args=parser.parse_args()
    print(json.dumps(reconcile(args.current,args.receipt,args.historic,args.manifest,args.outdir),indent=2))
