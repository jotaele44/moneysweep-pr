# MII v0.3 provisional ingestion

**State:** `PASS` for the bounded ingestion/reconciliation layer; **not** a
canonical entity or relationship promotion.

## Frozen source

The ingestion path is bound to the supplied MII v0.3 PDF and ZIP. The committed
`source_manifest.json` freezes outer SHA-256 values, byte sizes, PDF page count,
and the ZIP member path + uncompressed-size + SHA-256 inventory.

The ZIP describes a reference mockup rather than a production runtime. MoneySweep
therefore ingests source observations and aggregate ledgers without adopting the
mockup as canonical truth.

## What was materialized

A source run against the frozen PDF extracted:

- 256 rendered node-card manifestations from ecosystem pages 2–8;
- 182 distinct visible source-card signatures;
- 28 page-9 registry/name-only candidates;
- zero row-level edges.

The two generated row files are intentionally staging outputs, not committed
canonical records. Their expected hashes are frozen in `reconciliation.json`.

The 223-node aggregate denominator closes as `182 visible + 41 unmaterialized
row-level residue = 223`. The 41 residue is counted only. No placeholder rows are
invented.

The source reports 213 distinct edges and 59 cross-ecosystem edges while the ten
ecosystem boards sum to 272 edge appearances. The bounded arithmetic closes as
`(213 - 59) + 2*59 = 272`. The supplied source does not expose a complete
row-level 213-edge table, so the final row-level edge state is
`BLOCKED_SOURCE_ARTIFACT_NOT_EXPOSED`.

## Identity boundary

MII evidence classes A/B/C are preserved as source-local metadata only. They are
not translated into `resolution_core` binding evidence. A rendered card remains
an `UNRESOLVED` source manifestation until independent identity adjudication.

Page-9 registry candidates are explicitly
`CANDIDATE_NOT_IDENTITY / NAME_ONLY`. Count equality, same-sector membership,
normalization, and deterministic extraction never promote them.

## Contradictions

The six source contradictions `V3C-001..V3C-006` are preserved without
resolution. Two additional ingestion contradictions are explicit:

- `MII-INGEST-COUNT-001`: WATER declares four curated nodes, while its A+B+C
  node tally is three.
- `MII-INGEST-COUNT-002`: HEALTHSVC shows 208 core candidates in the coverage
  ledger while the final note says registry-only 2,175 candidates.

Neither discrepancy is silently reconciled.

## Source-vector binding

`source_bindings.json` maps the ten MII exhaustion vectors onto the current
MoneySweep source registry without claiming equivalence or completeness.

Current bounded gaps include FDA FEI/establishment registration, a dedicated PREB
docket adapter, FCC ULS/cable-license coverage, and a PRIDCO lease-roll adapter.
Existing registered or materialized sources are supporting routes only until the
MII-specific denominator and scope close.

## Local execution

With the exact source files available locally:

```bash
python3 scripts/import_mii_v03_reference.py \
  --check-reference \
  --pdf "/path/to/PR ecosystem network · MII v0.3.pdf" \
  --zip "/path/to/PR ecosystem network · MII v0.3.zip"
```

The importer refuses changed source hashes, changed ZIP members, extraction-count
drift, promoted name-only candidates, or incomplete PDF/ZIP pairing.
