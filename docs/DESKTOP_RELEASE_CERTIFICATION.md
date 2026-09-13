# MoneySweep Desktop Release Certification

## Claim boundary

The release claim is deliberately narrow:

> A specific distributed MoneySweep desktop artifact can be downloaded and
> opened by double-click on a clean supported machine without installing Python,
> Node, Homebrew, Conda, pip, npm, git, or runtime dependencies.

This claim does not imply that every network source is reachable, every API
credential is configured, every registered source is materialized, or the data
pipeline is production-valid.

## Identity layers

Keep these identities separate:

- **SOURCE_MANIFESTATION** — Git commit and Git object identities;
- **SOURCE_DENOMINATOR** — ordered/declared source universe, bound by the
  readiness artifact's source-ID SHA-256;
- **RUNTIME_RESOLUTION** — exact Python/build dependency inventory used by CI;
- **BYTE** — SHA-256 of each final distributed ZIP/DMG;
- **LOGICAL** — runtime self-test and source-count invariants;
- **DATA_STATE** — `production_status.json` and materialization validation.

Matching names, equal counts, a successful build, or a deterministic filename do
not prove BYTE identity.

## Required release gates

| Gate | Required evidence | Failure state |
|---|---|---|
| frozen source | exact commit recorded | BLOCKED |
| source denominator | source-ID SHA-256 + count closure | FAIL |
| full runtime | frozen executable imports real DuckDB + PyArrow | FAIL |
| producer candidate set | every registry-declared producer frozen | FAIL |
| workspace | writable state outside immutable app bundle | FAIL |
| idempotent boot | second boot does not overwrite user data | FAIL |
| no external runtime prerequisite | clean-machine launch needs no Python/Node/etc. | FAIL |
| offline core boot | UI + bundled seed data work without network | FAIL |
| API dry-run | source selection executes with zero producer calls | FAIL |
| secret non-disclosure | status/receipts return presence only | FAIL |
| OS credential vault | keyed source can be configured without plaintext workspace secret | FAIL |
| package provenance | exact package byte size + SHA-256 emitted | FAIL |
| macOS signing | strict `codesign` validation | BLOCKED |
| macOS notarization | stapler validation | BLOCKED |
| macOS Gatekeeper | `spctl --assess --type execute` | BLOCKED |
| production publication | `production_status == PRODUCTION_VALIDATED` | BLOCKED |

## Exact frozen self-test

The console form of the same PyInstaller build executes `--selftest` before the
windowed candidate is packaged. The self-test must demonstrate:

1. real `duckdb` imports;
2. real `pyarrow` imports;
3. workspace is outside application resources;
4. registered source count equals the bundled generated readiness artifact;
5. registry-driven dry-run selection equals `automatable_total`;
6. dry-run executes zero producers;
7. materialization status does not return secret values.

The old health-only smoke remains necessary but is no longer sufficient.

## Exact artifact manifest

Every matrix build must emit `DESKTOP_RELEASE_MANIFEST.json` beside the package.
For each package it records at least:

- source commit SHA;
- runner OS;
- source-ID-set SHA-256;
- registered/automatable counts;
- production state;
- distributed filename;
- distributed byte size;
- distributed SHA-256.

The resolved dependency inventory is retained beside the manifest and its
SHA-256 is included in the release evidence. This preserves the exact runtime
resolution even before a dedicated desktop lockfile is promoted.

## Public-release policy

CI artifacts may be produced while data remains diagnostic or while macOS code
signing infrastructure is absent. That permits testing without weakening the
release claim.

A `desktop-v*` public release is different. It fails closed unless:

- data state is exactly `PRODUCTION_VALIDATED`;
- the macOS app passes signing, stapled notarization, and Gatekeeper gates;
- the exact package hashes are emitted.

An unsigned test artifact must never be relabeled as the final double-click
release.

## Clean-machine certification

CI frozen-runtime self-tests are necessary but do not universally prove Finder
behavior. Before a release is marked `CERTIFIED`, test the exact downloaded
package on a clean supported macOS environment with no developer checkout and no
runtime tooling assumed.

Permitted operator actions:

1. download the distributed DMG/ZIP;
2. open/mount it normally;
3. double-click `PRII-MONEYSWEEP.app`.

Expected result: the native MoneySweep window reaches READY using bundled seed
data. Network is not required for core boot. Network is required only when the
operator explicitly initiates an API materialization operation or an online map
resource is requested.

## Certification states

- `PASS` — individual gate passed on the exact candidate;
- `FAIL` — gate executed and violated;
- `OPEN` — gate not yet executed;
- `BLOCKED` — prerequisite unavailable;
- `PROVISIONAL` — build candidate passed available automated gates but exact
  distributed clean-machine/Gatekeeper certification is incomplete;
- `CERTIFIED` — all gates for the defined release claim passed on the exact
  distributed artifact with zero unresolved residue inside that claim.
