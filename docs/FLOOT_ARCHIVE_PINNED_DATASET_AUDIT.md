# MoneySweep Floot archive pinned-dataset audit

Status: PROVISIONAL / BYTE-IDENTITY VERIFICATION OPEN

The archived Floot build hard-pins its upstream source to repository `jotaele44/moneysweep-pr` commit:

`fca326476f9811553888c4cc02a1fff20cc303fe`

The donor also embeds expected Git blob SHA-1, byte count, row count (where applicable), and SHA-256 for the mobile-release manifestations. These identities are discovery/binding inputs for exact upstream verification; they are not replaced by current `main` merely because filenames match.

## Canonical-v1 donor expectations

| Path | Bytes | Rows | SHA-256 | Git blob SHA-1 |
| --- | ---: | ---: | --- | --- |
| `data/canonical_v1/contracts.csv` | 1456 | 3 | `f0bad43fe0f63f6e767cf2d58f332df02014741fd23d0c86ac7c63609eefe486` | `1306ee050289b2e671873c636082fb469ae3544d` |
| `data/canonical_v1/entities.csv` | 7251 | 30 | `fdb0d63273f19c24341388ab1e36bfc70207408a716863c5f43ea47fbb257807` | `e6fedb51ec249e1a6b0995cc22b9ac036c61f8b3` |
| `data/canonical_v1/edges.csv` | 14995 | 66 | `f75472353a9f65fce85e6ce5cf3865267444bc7defd7cf12a7a02a25eadc4f59` | `d2b36f0dff4100c291c726e86331dc014e0585a0` |
| `data/canonical_v1/municipalities.csv` | 13108 | 78 | `4f7de46ba65ce9066e642fce7ca8661594311b60b0c794b85545a48f0ba31291` | `bee550978f122914acf1205f79058f9902d52f5a` |
| `data/canonical_v1/debt_instruments.csv` | 5708 | 20 | `886d9c3dbd87195c412fa945d56bf54d7c2a2fc5bdc800cd30af324c70e78523` | `f3b528d6d30fdce791af6a43bc37ae068a162d40` |
| `data/canonical_v1/evidence.csv` | 73347 | 260 | `90269860a949654c75879f9ea3551726b4b91cd8f12742c357925a93aa2d9e01` | `27faa150f6b987af2782e433037c2c7556c2dd57` |
| `data/canonical_v1/funding_sources.csv` | 820 | 4 | `dc3d9339e325bd5e7fc85a6ef7e0118a327b3dadfe63b76bd8758f5b23cc5d27` | `aa10ceb8e49c5cddaee0f7b04f6c06bc8b2b36c2` |
| `data/canonical_v1/people.csv` | 10469 | 60 | `10abe4f0210d9c56e182aee9f28eb018c31059105dd58deb617c897a0aa2ffdd` | `0eb26278cad4551603f48b624cfc624ae0f5bb3f` |
| `data/canonical_v1/projects.csv` | 2712 | 8 | `0b24087b205da7c03df1f8c9e16e896d23041ef2c06b51e123ac12bc2c1fc200` | `5a462ac968b193227508d3fe211d6916fac2a7b1` |
| `data/canonical_v1/properties.csv` | 1374 | 4 | `7780256370af86b91e8193957963c26d89a85128294729aa9d67864e2e602ba7` | `83037226812a59e50f0876d4cd5fbc2a95c10148` |

## Verification rule

Exact upstream verification should be performed against commit `fca326476f9811553888c4cc02a1fff20cc303fe`, not against mutable `main`.

A path is `BYTE_IDENTICAL` only when the fetched object at that commit matches the frozen content identity. Matching Git blob SHA-1 plus exact byte size is sufficient to bind the Git object manifestation; the donor SHA-256 remains an independent expected digest and should be recomputed when raw bytes are materialized.

Count equality alone never establishes byte or record identity.

## Current state

- donor pin recovered: PASS;
- donor expected hashes/counts recovered: PASS;
- exact upstream object verification at pinned commit: OPEN;
- local/mobile snapshot materialization: BLOCKED until exact upstream verification closes;
- current `main` must not silently replace the frozen donor snapshot.
