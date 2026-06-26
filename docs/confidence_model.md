# Confidence Model

Every exported row carries a `confidence` score: a float in `[0.0, 1.0]`
expressing how certain the producer is about that row (its identity,
attribution, and value).

- `1.0` — fully certain / directly observed in an authoritative source.
- `~0.9` — high-confidence derived or linked value.
- `< 0.9` — lower confidence; the consumer may choose to down-weight, flag for
  review, or exclude such rows.
- `0.0` — no confidence (should generally not be exported).

## Alignment with the existing repo

The export `confidence` reuses the same `[0.0, 1.0]` convention already used by
[`moneysweep/runtime/linkage_confidence.py`](../moneysweep/runtime/linkage_confidence.py),
which scores record linkage from weighted join signals and routes anything below
`MANUAL_REVIEW_THRESHOLD = 0.90` to manual review. Producers populating export
rows from linked data should carry that link score through as the row
`confidence`, so the federation sees the same scale the pipeline uses
internally.

## Suggested conventions

- Treat `0.90` as the manual-review threshold (matching the pipeline).
- Keep the scoring deterministic so re-runs over the same inputs yield the same
  `confidence` (consistent with deterministic IDs).
- Document any per-stream scoring rules in the producer that emits the rows.

## Validation

The validator fails closed when:

- `confidence` is absent → `confidence_missing`.
- `confidence` is not a finite number, or is outside `[0.0, 1.0]` →
  `confidence_out_of_range`.

See [validation_gates.md](validation_gates.md).
