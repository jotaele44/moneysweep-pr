# FY2022–FY2026 Puerto Rico assistance count acquisition

**Scope:** Ten read-only USAspending count queries, one each for FY2022–FY2026 × two distinct geography filters (Puerto Rico recipient location and Puerto Rico primary place of performance).

- Award type codes requested: 02–11 (grants, loans, direct payments, insurance and other financial assistance); no procurement/IDV codes or undocumented derived type `-1`.
- Raw request and response bytes, SHA-256, per-category source counts, and explicit fail-closed receipts are captured in a GitHub Actions artifact.
- No merged/union award population can be inferred from summing the two geography columns.
- No awards have been enumerated from these broad categories. In particular, counts over 10,000 must be safely partitioned before attempting pagination.
- FY2026 grant counts must reconcile against the previously frozen, independently enumerated 2,249 recipient-linked and 2,260 performance-linked award IDs.
- `SOURCE_COUNTS_ACQUIRED` does **not** imply program identity, complete FY universe, subaward coverage, SAM Active+Inactive coverage, TheHub consumption, production release, or certification.

**Release gate:** exact-head CI + independent review + full identity and source-population reconciliation, with all material findings closed. This draft is explicitly not production-ready.
