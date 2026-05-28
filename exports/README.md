# exports/

Staging area for Contract-Sweeper **federation export packages**.

Contract-Sweeper is a *producer* in the federation: it emits self-describing,
validated export packages that the **query hub** ingests. The query hub is not
an independent repo — it lives as the `query-hub` component inside the
[`spiderweb-pr`](https://github.com/jotaele44) repo. This directory is the
producer side of that cross-repo channel.

## Layout

```
exports/
  README.md             # this file
  samples/              # canonical, self-contained example package
    manifest.sample.json
    entities.sample.jsonl
    sources.sample.jsonl
    funding_awards.sample.jsonl
    transactions.sample.jsonl
    relationships.sample.jsonl
  build_<utc-timestamp>/   # throwaway packages written by build_export_package.py
```

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
