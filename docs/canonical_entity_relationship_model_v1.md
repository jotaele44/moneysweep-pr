# Canonical Entity Relationship Model v1

**Status:** schema-only (templates materialized; no data ingested yet)
**Version:** v1 · 2026-05-29
**Templates:** [`data/canonical_v1/`](../data/canonical_v1/)

---

## 1. Purpose

The Top250 power registry should not keep expanding as a flat list. This model
turns it into a typed graph so that each **person, entity, contract, debt
instrument, lobbying record, project, funding source, property, and
municipality** can be linked through typed, evidence-backed edges.

Every node and edge is meant to resolve to at least one **evidence** row.
Phrasing of any derived claim must follow
[`CLAIM_LANGUAGE_POLICY.md`](CLAIM_LANGUAGE_POLICY.md): use language such as
"record shows", "source states", "matched to", "linked with confidence X";
avoid conclusive language ("proves", "confirmed control") unless a claim is
strictly observed and directly sourced.

### Build sequence

Materialize and populate in this order. Do not score centrality until edge
completeness reaches minimum viable coverage.

1. Create empty schema templates. *(this step — done)*
2. Load Top250 people as `people.csv`.
3. Deduplicate entities from all known source surfaces.
4. Create `evidence` rows before graph edges.
5. Create edges only when source-backed.
6. Send unresolved name/entity conflicts to `review_queue.csv`.
7. Do not score centrality until edge completeness reaches minimum viable
   coverage.

---

## 2. Core tables

One CSV template per table in [`data/canonical_v1/`](../data/canonical_v1/).

| Table | Primary key | Function |
|-------|-------------|----------|
| `people.csv` | `person_id` | Individual actors |
| `entities.csv` | `entity_id` | Agencies, firms, funds, nonprofits, utilities |
| `roles.csv` | `role_id` | Person-to-institution positions |
| `contracts.csv` | `contract_id` | Public contracts, amendments, awards |
| `projects.csv` | `project_id` | Infrastructure, recovery, PPP, real-estate projects |
| `debt_instruments.csv` | `debt_id` | GO, COFINA, PREPA, PRASA, HTA, bond classes |
| `lobbying_records.csv` | `lobbying_record_id` | PR cabilderos / LDA filings |
| `funding_sources.csv` | `funding_source_id` | FEMA, HUD, EPA, DOE, CDBG-DR, ARPA |
| `revenue_streams.csv` | `revenue_stream_id` | Civilian-paid infrastructure income (tolls, fares, utility rates, port fees) |
| `properties.csv` | `property_id` | Hotels, land, concessions, facilities |
| `municipalities.csv` | `municipality_id` | Geographic anchors |
| `edges.csv` | `edge_id` | Typed graph relationships |
| `evidence.csv` | `evidence_id` | Source-backed claims |
| `review_queue.csv` | `review_id` | Unverified / ambiguous / conflicting records |

Each core node table carries provenance columns `confidence` (`0–1`),
`evidence_id` (FK into `evidence.csv`), and `review_status`
(`accepted` / `pending` / `rejected`).

---

## 3. Edge model

Use **one universal** `edges.csv`, not separate edge tables per tier.

| Field | Purpose |
|-------|---------|
| `edge_id` | Stable edge identifier |
| `source_node_type` | Person, Entity, Contract, Project, etc. |
| `source_node_id` | Source node ID |
| `edge_type` | Relationship verb (controlled vocabulary below) |
| `target_node_type` | Target node type |
| `target_node_id` | Target node ID |
| `start_date` | Temporal start |
| `end_date` | Temporal end |
| `amount` | Contract/debt/lobbying amount where known |
| `currency` | Usually USD |
| `confidence` | `0–1` |
| `evidence_id` | Link to `evidence.csv` |
| `notes` | Human-readable context |

### Controlled edge-type vocabulary

| `edge_type` | Meaning |
|-------------|---------|
| `HOLDS_ROLE_IN` | Person holds a position in an entity |
| `OWNS_OR_CONTROLS` | Ownership or control relationship |
| `REPRESENTS` | Legal/agent representation |
| `ADVISES` | Advisory relationship |
| `RECEIVES_CONTRACT` | Entity is awarded a contract |
| `FUNDED_BY` | Project/entity funded by a funding source |
| `LOCATED_IN` | Node anchored to a municipality |
| `HOLDS_DEBT` | Entity holds/issues a debt instrument |
| `NEGOTIATES_WITH` | Negotiation relationship |
| `SHARES_PERSONNEL_WITH` | Shared personnel between entities |
| `LOBBIES_FOR` | Lobbyist/firm lobbies for a client |
| `BENEFITS_FROM` | Node benefits from a contract/funding/project |
| `COLLECTS_REVENUE` | Agency collects infrastructure revenue from the public (income side) |
| `ALLOCATES_REVENUE_TO` | Agency directs collected revenue to operating spend/budget |
| `PLEDGED_TO_DEBT` | A revenue stream is pledged to a debt instrument (EMMA-disclosed) |

Edges using a verb outside this list should be routed to `review_queue.csv`
rather than written to `edges.csv`.

---

## 4. Evidence model

Evidence is first-class. Every graph edge should eventually resolve to at least
one `evidence.csv` row.

| Field | Purpose |
|-------|---------|
| `evidence_id` | Stable evidence key |
| `source_type` | PDF, CSV, web, filing, registry, court docket |
| `source_name` | Document or dataset name |
| `source_path_or_url` | File path or URL |
| `page_or_line_ref` | Page, row, or line reference |
| `claim` | Specific extracted claim |
| `evidence_tier` | `T1`–`T4` |
| `extraction_method` | manual, parser, OCR, API, web |
| `confidence` | `0–1` |
| `review_status` | accepted, pending, rejected |

---

## 5. Deterministic ID conventions

Use deterministic IDs. No random UUIDs for core nodes.

| Node | Pattern |
|------|---------|
| Person | `person_<normalized_name_hash>` |
| Entity | `entity_<normalized_name_hash>` |
| Contract | `contract_<agency>_<contract_number>` |
| Project | `project_<source>_<project_number>` |
| Debt | `debt_<issuer>_<class>_<year>` |
| Lobbying | `lobby_<jurisdiction>_<registration>_<quarter>` |
| Funding | `funding_<program>_<year>` |
| Municipality | `muni_pr_<normalized_name>` |
| Edge | `edge_<source>_<type>_<target>` |
| Evidence | `evidence_<source>_<row/page>_<hash>` |

---

## 6. Review queue

Unverified, ambiguous, or conflicting records go to `review_queue.csv`. This is
the canonical model's review surface and is **distinct** from the operational
`data/review_queue/` directory used by the source-recovery pipeline.

| Field | Purpose |
|-------|---------|
| `review_id` | Stable review identifier |
| `object_type` | Node/edge/evidence type under review |
| `object_id` | ID of the object under review |
| `issue_type` | Nature of the issue (ambiguous, conflicting, unverified, ...) |
| `raw_value` | Raw observed value |
| `candidate_match` | Candidate canonical match, if any |
| `source_name` | Source document/dataset |
| `source_ref` | Page/row/line reference |
| `severity` | Triage severity |
| `recommended_action` | Suggested resolution |
| `status` | Queue status |

---

## 7. Source mapping notes

Initial source surfaces and how they map into the model:

- **ACT transition contracts** are already graph-useful: they expose
  contractor, contract number, service type, dates, and amount. For example,
  *Autopistas Metropolitanas de Puerto Rico* appears on long-term ACT
  agreements ending in 2051 with billion-dollar values, mapping into
  Entity → Contract → Agency → Project/Concession edges.
- **ACUDEN transition records** enter the same schema as transfer-fund
  contracts: municipalities and private recipients map to Entity nodes;
  fund-transfer records map into `contracts.csv`.
- **PRASA/AAA completed projects** map directly into `projects.csv`, with
  municipalities as anchors and PRASA as applicant/agency.
- The **PRASA FY2024 Consulting Engineer Report** is a strong source (fiscal
  situation, federal funds, capital improvement program, board/executive
  management tables, CIP project tables).
- The **Puerto Rico lobbying registry** links lobbying firms, clients, and
  authorized personnel — e.g. *LGA Strategies* clients such as Genera PR and
  Puerto Rico Energy LLC, and *The RCL Group* clients such as Arcadis Caribe,
  Global Ports Holdings, and Puerto Rico Municipal Financing.
- The **federal LDA extract** is the federal lobbying counterpart, especially
  for records involving the Puerto Rico Fiscal Agency and Financial Advisory
  Authority and the Puerto Rico Public-Private Partnership.

---

## Appendix — Relationship to the existing canonical model

This v1 model is an **additive, schema-only layer**. It does not modify the
repo's existing JSON-schema canonical artifacts or the federation export
contract (v1.2.0, synced with `spiderweb-pr`). The two models overlap and are
expected to be bridged later:

| v1 (this doc) | Existing model |
|---------------|----------------|
| `people.csv` + `entities.csv` | `entities.jsonl` (`schemas/contract_sweeper_entity.schema.json`), unified via `entity_type` |
| `edges.csv` | `relationships.jsonl` (`schemas/contract_sweeper_relationship.schema.json`) |
| `evidence.csv` | `sources.jsonl` (`schemas/contract_sweeper_source.schema.json`) + `lineage` |
| `contracts.csv` / `funding_sources.csv` | `funding_awards.jsonl` (`schemas/contract_sweeper_funding_award.schema.json`) |
| `municipalities.csv` | `data/reference/pr_municipalities.csv` |
| `evidence_tier` `T1`–`T4` | claim tiers in `CLAIM_LANGUAGE_POLICY.md` (Observed / Linked / Inferred / Risk / Blocked) |
| semantic IDs (`person_<hash>`, `contract_<agency>_<num>`) | deterministic hash IDs (`ent_/rel_/src_/awd_/txn_<32hex>`) |

A future "bridge" step can reconcile the v1 semantic IDs and `evidence_tier`
values with the existing hash IDs and claim-tier vocabulary. Until then, v1
artifacts stand alone and ingest no data.
