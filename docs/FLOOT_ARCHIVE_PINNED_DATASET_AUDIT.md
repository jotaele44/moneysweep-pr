# MoneySweep Floot archive pinned-dataset audit

Status: PROVISIONAL / GIT-OBJECT IDENTITY PASS / INDEPENDENT REMOTE SHA-256 REHASH OPEN

The archived Floot build hard-pins its upstream source to repository `jotaele44/moneysweep-pr` commit:

`fca326476f9811553888c4cc02a1fff20cc303fe`

The donor embeds exact path, Git blob SHA-1, byte count, row count where applicable, and SHA-256 for 19 mobile-release manifestations. Verification is performed against the pinned commit, never mutable `main`.

## Frozen donor expectations and pinned-object adjudication

| Path | Bytes | Rows | Donor SHA-256 | Expected Git blob SHA-1 | Pinned object |
| --- | ---: | ---: | --- | --- | --- |
| `data/canonical_v1/contracts.csv` | 1456 | 3 | `f0bad43fe0f63f6e767cf2d58f332df02014741fd23d0c86ac7c63609eefe486` | `1306ee050289b2e671873c636082fb469ae3544d` | PASS |
| `data/canonical_v1/entities.csv` | 7251 | 30 | `fdb0d63273f19c24341388ab1e36bfc70207408a716863c5f43ea47fbb257807` | `e6fedb51ec249e1a6b0995cc22b9ac036c61f8b3` | PASS |
| `data/canonical_v1/edges.csv` | 14995 | 66 | `f75472353a9f65fce85e6ce5cf3865267444bc7defd7cf12a7a02a25eadc4f59` | `d2b36f0dff4100c291c726e86331dc014e0585a0` | PASS |
| `data/canonical_v1/municipalities.csv` | 13108 | 78 | `4f7de46ba65ce9066e642fce7ca8661594311b60b0c794b85545a48f0ba31291` | `bee550978f122914acf1205f79058f9902d52f5a` | PASS |
| `data/canonical_v1/debt_instruments.csv` | 5708 | 20 | `886d9c3dbd87195c412fa945d56bf54d7c2a2fc5bdc800cd30af324c70e78523` | `f3b528d6d30fdce791af6a43bc37ae068a162d40` | PASS |
| `data/canonical_v1/evidence.csv` | 73347 | 260 | `90269860a949654c75879f9ea3551726b4b91cd8f12742c357925a93aa2d9e01` | `27faa150f6b987af2782e433037c2c7556c2dd57` | PASS |
| `data/canonical_v1/funding_sources.csv` | 820 | 4 | `dc3d9339e325bd5e7fc85a6ef7e0118a327b3dadfe63b76bd8758f5b23cc5d27` | `aa10ceb8e49c5cddaee0f7b04f6c06bc8b2b36c2` | PASS |
| `data/canonical_v1/people.csv` | 10469 | 60 | `10abe4f0210d9c56e182aee9f28eb018c31059105dd58deb617c897a0aa2ffdd` | `0eb26278cad4551603f48b624cfc624ae0f5bb3f` | PASS |
| `data/canonical_v1/projects.csv` | 2712 | 8 | `0b24087b205da7c03df1f8c9e16e896d23041ef2c06b51e123ac12bc2c1fc200` | `5a462ac968b193227508d3fe211d6916fac2a7b1` | PASS |
| `data/canonical_v1/properties.csv` | 1374 | 4 | `7780256370af86b91e8193957963c26d89a85128294729aa9d67864e2e602ba7` | `83037226812a59e50f0876d4cd5fbc2a95c10148` | PASS |
| `reports/current_status.json` | 8948 | — | `5fb9a261472a67f2abbd09125b27122aec0cc345cce517f72ba3a7d5747876d0` | `ae035b10d84231dd45ea1e18b4e16cca670634e3` | PASS |
| `reports/materialization_readiness.json` | 1038 | — | `b0c1f87957d74e7b26b9e887bf32e711312a671a779adabcab5a2ce4155216ca` | `975da2fd5a270ee8b807b0237240edb99e765e5f` | PASS |
| `reports/source_registry_status.csv` | 51800 | 164 | `9253c0c59b714363d0ea8d5efae4f1de00f5f63cb18264e8e57d35b4faed6bb3` | `0729fbf0847ff41b5593d9443f339aa073fa2511` | PASS |
| `.federation/admin-boundary.json` | 318 | — | `743ef486a0500b189e8cce2591583ce34380b81610cffe57010788033a534909` | `69810ea909cdfea4f6f9e7e95a798cfe0c4ad1ef` | PASS |
| `.federation/gui-capabilities.json` | 69650 | — | `1c811bcec2072e0bd14f9e634db00fe15bf58915d11fdb342002995ecb1a77f1` | `c073b2e93efae9fe74dac47c0a4c2f686587eda8` | PASS |
| `.federation/gui-capabilities.extensions/desktop-data-materialization.json` | 2764 | — | `92ca9818ed1c22d5bc8cadf5f591d2f51d9efac8279c33b29e78432126e7c3aa` | `1e1f8498fc990725b4eecf4c0e9c830a98223706` | PASS |
| `.federation/gui-capabilities.extensions/ownership-deep-dive-v1.json` | 2332 | — | `bc307b583f7967f1db3a9edad8a618f8c9f58e4847a92ee3719ff16b59827f59` | `fa0db7dd002fba6d8008de0cfc2c70a19ce2070e` | PASS |
| `data/derived/government_organization_change_events.json` | 74 | — | `ecd54c2a4fc65699cd2cbf814996b263e8bb3492533c956c128595e757b420f5` | `d07110a5d197b70843e1be7c538ec5af6cc928a1` | PASS |
| `data/staging/processed/government_organization_change_candidates.json` | 136 | — | `6443630bf722088a2305002b346266c0960de584378ca010d54e416994909627` | `db17ce98a674e095866e58a4b6bac721fe6bdfb6` | PASS |

## Identity result

For all 19 donor-declared manifestations, the object at the exact pinned commit has the same repository path, Git blob SHA-1, and byte size as the donor contract. This establishes exact Git-object manifestation identity for the bounded set: **19/19 PASS**.

This does not substitute count equality for identity. Row counts remain invariant checks only. The stable binding is exact commit + path + Git blob object identity; byte size is an additional conservation check.

The donor SHA-256 values remain separately frozen. Raw GitHub transport is unavailable in the current execution environment, so those remote objects have not yet been independently materialized and rehashed with SHA-256 during this reconciliation run. That additional BYTE-identity cross-check remains OPEN rather than being inferred from the Git object match.

## Current state

- donor pin recovered: PASS;
- donor expected 19/19 content identities recovered from original archive: PASS;
- pinned commit resolves: PASS;
- exact pinned Git object + path + byte-size verification: PASS 19/19;
- independent remote SHA-256 rehash: OPEN;
- row-count equality: INVARIANT ONLY, never identity proof;
- local/mobile snapshot materialization: PROVISIONAL pending the independent SHA-256 cross-check or an explicit bounded decision that the exact Git-object binding is sufficient for this release surface;
- current `main` must not silently replace the frozen donor snapshot.
