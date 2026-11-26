# MoneySweep financial and economic intelligence scope v1

**Status:** candidate, not adopted. **Certification:** WITHHELD. **Production adoption:** BLOCKED.
**Baseline:** `main` at `d5a443ef6425d09181f1481d14dd2a5d286dc6af`, audited 2026-11-26.

This document specifies an expansion of MoneySweep from a set of public-money source
lanes into one financial and economic intelligence model for Puerto Rico. It records what
the repository held at the baseline, what this candidate adds, and what stays open.

The candidate adds a classification and conservation layer. It changes no existing
export stream, schema, identifier, API or dashboard view, and it populates no data.

## 1. What the system must be able to answer

1. Who owns Puerto Rico's economic assets?
2. Who finances, operates and controls those assets?
3. Where does capital originate, circulate and ultimately accumulate?
4. Who benefits from government expenditures, contracts, subsidies and incentives?
5. What financial dependencies exist between public, private, domestic and foreign entities?
6. How have these relationships changed historically?

## 2. Baseline audit

Every statement here is read from a committed file at the baseline commit.

| Finding | Evidence |
|---|---|
| The repository is not production-certified: `NON_PRODUCTION_DIAGNOSTIC`. | `STATUS.md`, `federation.json` |
| Three production blockers stand: 3 of at least 8 data layers populated, 18 of at least 100 entities, and fixture data detected. | `data/exports/production_status.json` (2026-07-28) |
| 167 sources are registered. 20 are fully materialized, 3 partially, 144 not. | `reports/source_registry_status.csv` |
| No source has a recorded scheduled success. | `reports/source_freshness.csv`, per `STATUS.md` |
| Identity adjudication already has one engine with fail-closed rules. | `moneysweep/capital_control/resolution_core` |
| Relationships and money movement are already separated by rule. | `moneysweep/entity_network` |
| Amounts already have an exact-decimal, source-bound form. | `moneysweep/financial_classification_v1.py` |
| The legacy flow table uses random `flow_id` values and sums different financial stages. | `docs/FINANCIAL_FLOW_COMPATIBILITY_V1.md` |
| Certified ownership data covers one issuer: Popular, Inc. (BPOP), eight 13F quarters. | `docs/OWNERSHIP_AND_CAPITAL_DEEP_DIVE_V1.md` |
| There is no Foreign Connections module, schema or certified source. | No path under `moneysweep/`, `schemas/` or `registries/` |
| No registered source covers foreign-agent registration (FARA). | `registries/source_registry.json` and its extensions |

Two structural observations follow from the audit and shape the design.

**The foundations the proposal asks for at P0 mostly exist.** A unified entity registry,
an evidence contract and a transaction identity were listed as the first priority. The
repository already has the identity engine, the evidence states and the source-bound
amount. What it lacked was a transaction identity that survives being viewed from several
domains, a dated ownership model, and a continuity model. Those three are what this
candidate adds.

**Five vocabularies describe entities and relationships, and nothing reconciles them
inside this repository:** `canonical_v1` (15 edge verbs), `schemas/forensics`, the
federation export schemas, the entity-network kernel (8 relationship families) and the
government-entity relationship types. This candidate binds to the kernel and the
resolution core and does not attempt that reconciliation.

One inconsistency was found in the reused primitives and is left as found:
`MoneyFlowObservation.amount` in `moneysweep/entity_network/models.py` is a `float`,
while `financial_classification_v1` rejects floats and carries exact decimal strings.
The candidate uses exact decimals.

## 3. Frozen capabilities

No file that existed at the baseline is modified. Capability parity was checked by running
the existing test suite, the lint and type gates and the GUI parity gate on the candidate
tree (section 9). The candidate's own modules are registered as
`internal` in `.federation/gui-capabilities.extensions/financial-intelligence-v1-internal.json`
because no human-facing workflow reads them.

## 4. The ontology

The machine-readable source of truth is `registries/financial_intelligence_ontology_v1.json`,
shaped by `schemas/financial_intelligence_ontology.schema.json` and checked by
`moneysweep.financial_intelligence.ontology.validate_ontology`.

| Element | Count | Notes |
|---|---:|---|
| Domains `MS01`–`MS25` | 25 | Each names the foundations it reuses |
| Foreign Connections relationship classes | 9 | Bound to kernel relationship families; capital relationships bind to money flow |
| Flow kinds | 8 | 3 directions and 5 characters; see below |
| Entity groups | 6 | 36 kinds, each mapped to an existing node kind |
| Continuity dimensions | 7 | Independent of one another |
| Historical periods | 7 | 1898 to present; analytical, not exclusive |
| Analytical capabilities | 20 | Each carries a guardrail |
| Infrastructure classes | 14 | Identity owned outside MoneySweep |
| Source authority ranks | 6 | Ranks 5 and 6 are discovery leads only |
| Scope policies | 10 | As proposed |

The ontology is an overlay. A domain is a view over shared entities, relationships and
transactions; it has no table of its own. That is how one acquisition by a foreign
state-owned enterprise of a Puerto Rico infrastructure operator can appear under Foreign
Connections, Government-Linked Capital, Corporate Ownership, Strategic Infrastructure and
Public-Private Partnerships while remaining one transaction.

### Where the candidate departs from the proposal

These are design decisions made while implementing. Each can be reversed.

1. **The eight flows are two axes, not one list.** Inbound, outbound and internal exclude
   one another and follow from where the two parties are. Pass-through, retained,
   extracted, noncash and contingent describe the kind of movement and can combine with
   any direction, so each needs its own evidence. A noncash outbound asset transfer is
   both.
2. **Transaction identity is the source-native record, nothing else.** The identity is a
   hash of source, source record and event type. Amount, date, parties, file hash and
   domains are excluded, so a re-retrieved snapshot or a new domain view is the same
   transaction. Two sources reporting the same deal produce two identities until a
   certified equivalence joins them. Matching amounts, dates or names is not an
   equivalence.
3. **Ownership tracing does not report an "ultimate owner".** A chain ends either
   `UNRESOLVED` (unknown holder or uncertified link) or `NO_FURTHER_RECORD` (the corpus
   holds nothing above this holder). Absence from the corpus is not evidence that the
   chain stops there.
4. **Seven domains carry no priority.** The proposal's priority table does not place
   Public Expenditures, Public Revenues, US Mainland Connections, Financial Compliance or
   Nonprofit Finance, and Political Finance and Lobbying were already in scope. They are
   marked `UNASSIGNED` or `EXISTING_SCOPE` rather than given a priority the proposal did
   not state.
5. **"Advanced economic modeling" (P5) has no domain.** It is a capability class, not one
   of the 25.

## 5. The candidate kernel

`moneysweep/financial_intelligence/` holds pure functions over in-memory inputs.

| Module | Provides |
|---|---|
| `transactions.py` | `mstx_` identity, disclosure and valuation gates, domain membership, certified equivalence, unique totals, flow direction and character |
| `ownership.py` | Dated intervals for five interest kinds, share conservation, upward tracing |
| `continuity.py` | Seven-dimension status profile on a date |
| `ontology.py` | Registry loader, structural gates, check that every reused primitive still resolves |
| `coverage.py` | Projection of the registered source denominator onto the 25 domains |

Identity, evidence states and exact-decimal handling are imported from the existing
primitives, not reimplemented.

## 6. Data inventory

`reports/financial_intelligence_domain_coverage_v1.md` projects the 167 registered sources
and 5 known unregistered candidates onto the domains, from the bindings in
`registries/financial_intelligence_source_bindings_v1.json`.

- All 172 are accounted for: 164 bound to at least one domain, 8 explicitly unbound with a reason.
- 24 of 25 domains have at least one registered source. `MS24` Intellectual Property & Royalties has none.
- 13 domains have no source producing output now.
- Of the four P1 domains, Government-Linked Capital has two registered sources and neither is producing output.

The bindings were assigned from each source's registry identity and family. They say a
source is a candidate input to a domain. They say nothing about its rows, and they are
not coverage.

## 7. Federation boundaries

MoneySweep consumes certified asset identities and geometries from the repository that
owns them. It does not register assets. The ontology names a candidate owner for 5 of the
14 infrastructure classes and leaves 9 unassigned; none is ratified. The proposed
partition is submitted to the hub as `thehub-pr` ADR 0018, which is Proposed, not
Accepted.

Until an owner is ratified for a class, MoneySweep can hold financial relationships about
assets of that class only against source-native identifiers, and cannot claim a federated
asset identity.

## 8. Failure modes

Each guarded failure mode names its test in
`tests/test_financial_intelligence_kernel_v1.py` or
`tests/test_financial_intelligence_ontology_v1.py`.

| ID | Failure | Guard |
|---|---|---|
| FM01 | A transaction in several domains is counted several times | `test_one_transaction_in_five_domains_is_counted_once` |
| FM02 | Identity changes when a snapshot is re-retrieved | `test_identity_ignores_snapshot_amount_and_domains` |
| FM03 | One identity carries conflicting content | `test_conflicting_manifestations_of_one_identity_fail_closed` |
| FM04 | Two sources are merged because they look alike | `test_only_certified_equivalence_merges_two_sources` |
| FM05 | Certified equivalents disagree on amount | `test_equivalent_transactions_that_disagree_fail_closed` |
| FM06 | An undisclosed amount becomes zero | `test_unknown_amount_stays_unknown_and_records_its_limitation` |
| FM07 | Different currencies or valuation bases are summed | `test_mixed_currency_or_valuation_basis_cannot_be_summed` |
| FM08 | Float, negative or basis-free amounts are accepted | `test_invalid_transactions_are_rejected` |
| FM09 | Guarantees and asset swaps enter a cash total | `test_guarantees_and_asset_swaps_never_enter_a_cash_total` |
| FM10 | Direction is guessed when a party's jurisdiction is unknown | `test_direction_comes_only_from_resolved_jurisdictions` |
| FM11 | A flow is both retained and extracted | `test_retained_and_extracted_on_one_transaction_is_a_conflict` |
| FM12 | An unevidenced domain label is projected | `test_unevidenced_membership_is_not_projected` |
| FM13 | An intermediate or unknown holder is reported as the owner | `test_unknown_or_uncertified_link_ends_the_chain_unresolved` |
| FM14 | A parent company is reported as beneficial owner | `test_a_parent_is_not_a_beneficial_owner` |
| FM15 | An unknown share is treated as zero or one | `test_unknown_share_propagates_as_unknown_not_zero` |
| FM16 | Certified shares exceed 100% | `test_certified_shares_cannot_exceed_the_whole` |
| FM17 | Circular ownership loops or resolves arbitrarily | `test_ownership_gates` |
| FM18 | Ownership is reported for the wrong date | `test_ownership_is_dated` |
| FM19 | An operated asset is read as an operating company | `test_operated_assets_do_not_prove_an_operating_company` |
| FM20 | One of two conflicting statuses is silently chosen | `test_conflicting_certified_statuses_are_kept_as_a_conflict` |
| FM21 | Pre-1898 evidence enters without a justification | `test_pre_1898_evidence_needs_a_justification` |
| FM22 | The ontology drifts from the code it describes | `test_structural_drift_fails_closed`, `test_every_reused_primitive_still_resolves` |
| FM23 | MoneySweep becomes a competing asset registry | `test_moneysweep_owns_no_infrastructure_registry` |
| FM24 | Press or aggregator data establishes a fact | `test_secondary_sources_establish_nothing` |
| FM25 | A source is dropped from, or invented in, the denominator | `test_source_denominator_is_conserved`, `test_phantom_and_contradictory_bindings_fail_closed` |
| FM26 | Adoption is unblocked without certification | `test_candidate_is_not_adopted`, `test_structural_drift_fails_closed` |

### Failure modes with no guard yet

| Failure | Why it is unguarded |
|---|---|
| Nationality or foreign status used as a risk signal | The candidate has no risk classifier to constrain; the rule is policy text only |
| Sensitive personal data admitted to a person record | The candidate defines no person record; the restriction is policy text only |
| A source acquired outside lawful access | Acquisition is out of this candidate's scope |
| Revenue measured with spending vocabulary | `financial_classification_v1` measures cover spending only |
| Amounts compared across decades without a price year | No valuation-date field exists yet |
| Correlation presented as causation in an output | No analytical output exists yet; guardrails are text on each capability |
| Cross-vocabulary edge mismatch | The five relationship vocabularies are not reconciled |

## 9. Certification gates

State of each gate on this candidate. "Synthetic" means proven on constructed test inputs
only; no real source row has passed through the candidate.

| Gate | State | Basis |
|---|---|---|
| Accuracy | OPEN | No real data processed |
| Completeness | OPEN | All 25 domains `DEFINED_NOT_POPULATED`; one has no source |
| Consistency | PASS within the candidate; OPEN across legacy vocabularies | Registry and code are cross-checked on load |
| Entity identity | Reused unchanged | `resolution_core` |
| Beneficial ownership | Primitive only, synthetic | `ownership.py` |
| Government control | OPEN | `CONTROL` is an interest kind; no public-holder test exists |
| Temporal validity | Primitive only, synthetic | Dated intervals and the 1898 rule |
| Transaction conservation | Primitive only, synthetic | Unique totals over canonical identities |
| Financial reconciliation | OPEN | No reconciliation against a source total |
| Provenance | Partial | Record-level source, record id and byte hash; field-level traceability not implemented |
| Failure tests | 26 guarded, 7 unguarded | Section 8 |
| Existing-capability parity | PASS on this tree | 3,372 existing and new tests pass; the 5 failures in `tests/test_act_acuden_extractor.py` fail identically on the untouched baseline |
| Adoption authorization | Not requested | Blocked until the gates above close |

## 10. What this candidate does not do

- It acquires no source and materializes no data.
- It adds no API endpoint, export stream or dashboard view.
- It does not reconcile the legacy flow table or replace any legacy identifier.
- It does not deliver the 20 analytical capabilities. 10 are specified only, 6 are partly
  served by modules that already existed, and 4 have a first primitive here.
- It ratifies no federation ownership boundary.
- It certifies nothing.

## 11. Open decisions

1. Priority for the five domains the proposal left unplaced.
2. Whether `cms_open_payments` and `opm_fedscope` belong to a domain or stay out of scope.
3. Owners for the nine unassigned infrastructure classes.
4. Whether to align `MoneyFlowObservation.amount` with exact decimals.
5. Which of the five relationship vocabularies becomes canonical.

## 12. Regenerating

```bash
python -m moneysweep.financial_intelligence.coverage          # rewrite the coverage report
python -m moneysweep.financial_intelligence.coverage --check  # fail if it is stale
python -m pytest tests/test_financial_intelligence_kernel_v1.py tests/test_financial_intelligence_ontology_v1.py --no-cov
```
