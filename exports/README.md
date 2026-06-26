# exports/

Staging area for moneysweep-pr **federation export packages**.

moneysweep-pr is a *producer* in the federation: it emits self-describing,
validated export packages that the **query hub** ingests. The query hub is not
an independent repo — it lives as the `query-hub` component inside the
[`spiderweb-pr`](https://github.com/jotaele44) repo. This directory is the
producer side of that cross-repo channel.

## Layout

```
exports/
  README.md             # this file
  samples/              # canonical, self-contained example package (synthetic)
    manifest.sample.json
    entities.sample.jsonl
    sources.sample.jsonl
    funding_awards.sample.jsonl
    transactions.sample.jsonl
    relationships.sample.jsonl
  conformance/v1_2/     # non-synthetic cross-repo conformance package (see below)
  build_<utc-timestamp>/   # throwaway packages written by build_export_package.py
```

## Cross-repo conformance (v1.2.0)

`conformance/v1_2/` is a committed, **non-synthetic** package in the current
`1.2.0` on-wire shape. A byte-identical copy lives in the consumer repo at
`spiderweb-pr/tests/fixtures/moneysweep_v1_2/`, where
`tests/test_moneysweep_conformance.py` ingests it through the consumer's
adapter + production gate + contract-finance layer. This pair guards against the
contract-drift incident in which both repos shipped incompatible "1.1.0"
definitions — see the consumer-side report at
`spiderweb-pr/docs/contracts/CONTRACT_FINANCE_CONNECTIVITY_HEALTH.md`.

* `samples/` is the small, committed example used by `scripts/smoke_export.py`
  and as documentation of the on-the-wire shape. Files carry a `.sample` infix;
  the builder strips it when packaging.
* `build_<utc-timestamp>/` directories are produced by
  `scripts/build_export_package.py` when run without `--output-dir`. They are
  throwaway build artifacts — do not commit them.

> Note: the pre-existing `data/exports/` directory is owned by the R5 status
> pipeline and is unrelated to federation export packages. It is left
> untouched.

## Build and validate

```bash
# Build a package from the bundled samples into a fresh directory:
python scripts/build_export_package.py --output-dir exports/build_demo

# Validate it (fail-closed):
python scripts/validate_export.py --package exports/build_demo --mode test

# End-to-end smoke (build to a tempdir + validate), no network:
python scripts/smoke_export.py
```

## Package contract

Every package is a directory containing `manifest.json` plus five JSONL stream
files. The manifest declares the cross-repo `federation` handshake
(`consumer_repo: spiderweb-pr`, `consumer_component: query-hub`) and lists each
stream file with its `sha256`, `record_count`, and `schema_id`. The single
compatibility key the hub checks on ingest is `export_contract_version`.

See [`docs/export_contract.md`](../docs/export_contract.md) for the full
specification and [`docs/federation_readiness.md`](../docs/federation_readiness.md)
for the cross-repo topology.
