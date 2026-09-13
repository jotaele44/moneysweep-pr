# Certification truth hardening: bounded implementation, not production certification

## Exact continuation and authority boundary

Base: `50a44d0834e04c1ef422ae859c4671fb4972291c`, the open draft continuation
PR #565. PR #531 is closed and unmerged. PR #588 proposes current-main
reconciliation and is not incorporated here. This change is a stacked draft;
it does not merge either PR, change main, activate production, or rewrite
historical Wave-0 reports.

The frozen 162-source / 16-required / 113-automatable / 49-excluded population
remains a binding target, NOT a newly observed successful execution count.
Current-main registry reconciliation remains OPEN. Counts alone cannot prove
that the current and historical populations have identical members.

## Implemented in this patch

- Explicit CSV materialization contracts: `min_rows` and `required_columns`.
  Optional `csv.encoding`, `csv.delimiter`, and zero-based `csv.header_row`
  support declared preambles and source-specific parsing. Raw headers remain
  unchanged. Malformed minima, duplicate/empty headers, ragged rows, bad
  encodings, escaping paths and symlinks do not receive materialization credit.
- Positive-row counts are not a schema proof. Non-tabular and directory outputs
  remain unproven until their dedicated validators are implemented. No production
  source contract or threshold is invented or weakened by this patch.
- Strict receipt discovery rejects duplicate source IDs, malformed JSON,
  duplicate JSON object keys, non-finite numbers and unclassified entries.
  Receipt outputs are rebound to measured path, SHA-256, bytes and rows;
  source ID, producer path, registry ID digest and complete source definition
  must also match. Whole candidate collisions are rejected, not first-wins.
- A versioned execution consistency check requires an evidence-receipt digest,
  matching producer commit, ordered timezone-aware timestamps, success status,
  usable outputs and a valid bound receipt. Missing execution is NOT_ATTEMPTED.
  Readiness is computed from these per-source observations, not automatable count.
- Freshness requires a declared basis. Unknown cadence/SLA/basis, invalid
  receipts, naive timestamps and future timestamps remain unproven. A declared
  one-time archival basis is distinct from a periodic freshness SLA. Manual
  required sources are not automatically exempt from freshness evaluation.
- Truth and scope schemas advance to v2. Scope identity binds registry artifact
  hashes, complete source-definition identity, generation-tool hashes, configuration,
  evidence receipt identities, truth identity and report inventory. Existing or
  interrupted scope directories are never overwritten. The manifest is written
  last; interrupted scopes without it cannot be consumed as completed scopes.
- The certifier recomputes scope identity and artifact inventory, uses per-source
  execution/coverage observations for G5/G6, and will not use a historical status
  CSV alone to pass G3. G7's conservative advisory/blocking policy is unchanged.
- Default diagnostic output is content-keyed under build/, written exclusively.
  Configuration cannot rename a failed result CERTIFIED.

## Explicit migration interlocks: not completed verifiers

G8, G9, G11 and G12 remain BLOCKED until their scope-bound verification paths are
implemented and validated. Historical corpus-authority, canonical-status,
federation-readiness and activation fields are preserved as observations but
cannot promote the release. These are intentional temporary interlocks, not
claims that replay, lineage, signatures or protected activation are implemented.

The truth generator may still inspect a diagnostic evidence workspace. A supplied
`--operator-corpus-id` is labelled an unverified claim. The seven-layer production
restriction to a verified CAS-derived mount is NOT complete in this patch.
Integrity hashes and internally consistent receipts do not authenticate a producer
or prove that declared source coverage matches the real-world universe.

## Execution receipt compatibility

The minimal consistency envelope is `moneysweep.source_execution/v1` with:
`source_id`, `evidence_receipt_sha256`, `producer_git_sha`, `execution_status`,
`started_at`, `completed_at`, and `schema_version`.

`evidence_receipt_sha256` is a LOGICAL digest using the repository's sorted,
compact, UTF-8 Python JSON profile, not a raw-byte hash and not an RFC 8785 claim.
Raw-byte receipt freezing and authenticated producer attestations remain required
for the completed trust root. Existing keyless workflow receipts are not silently
converted to this envelope. A documented, tested adapter must conserve original
receipt bytes and reconstruct only facts actually present in the source evidence;
otherwise they remain EXECUTION_UNPROVEN.

CSV schema or freshness contract additions change source-definition identity.
Old receipts cannot inherit those additions merely because source IDs match.
Preserve old receipts and either obtain fresh bound evidence or approve a formal
scope/contract transition with explicit provenance. Do not edit receipt digests
in place to manufacture compatibility.

## Bounded verification and limitations

The local verification scope is the self-contained guard tests, state-expression
regression tests, static wiring assertions and Python compilation of the changed
files. The original certifier, truth engine and existing truth test were retained
byte-for-byte and checked against their authoritative Git blob IDs before editing.

This is NOT the full repository suite, coverage ratchet, mypy, GUI parity, hosted
CI, a 162-source live execution, a CAS replay, or a production certificate.
The local environment could not clone the complete repository, and the branch's
pinned Ruff 0.16.4 was unavailable offline. Lint/format and integration remain OPEN.
The existing positive CSV fixture now declares its schema; production thresholds
are unchanged. The complete original test suite must still be run in the repository.

Remaining implementation: complete source-specific validation contracts (including
keys/nulls/coverage/joins and non-tabular adapters); authoritative publication-time
freshness adapters; authenticated raw receipts; crash-safe streaming and
race-resistant CAS reads; exact excluded-ID reconciliation; verified corpus-only
truth replay; canonical and federation receipts; the blocker DAG; protected
activation verification; GUI exposure of eventual operator-facing outcomes.

`--require-certified` retains its existing strict release meaning and is not a
pre-activation eligibility command. Its successful execution was not established
here. The later two-stage release design must separate technical eligibility from
activation without redefining a diagnostic report as CERTIFIED.

No COR3/HUD/FEC alternative was substituted, no credentials were sought or used,
and no source acquisition or 113-source execution completion is claimed here.
