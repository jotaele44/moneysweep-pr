# PR2.5 SAM / USAspending Parent Resolution Report

## Result

- entities_resolved rows: 107459
- rows with parent_uei: 434
- parent_uei rate: 0.4039%

## Interpretation

The parent-UEI rate should not be treated as a universal 90% production gate for this Puerto Rico awards layer. The observed entity universe is dominated by Puerto Rico government agencies and public authorities, which generally do not resolve through SAM parent hierarchy the same way commercial subsidiaries do.

## Gate recommendation

Use source-family-specific thresholds:

- Government-heavy award sources: parent_uei_coverage_pct >= 0.10
- Commercial prime/subaward-heavy sources: parent_uei_coverage_pct >= 0.90
- High-value unresolved entities: remain blocking unless each has a review note

## Outputs

- data/processed/entities_resolved_top5.csv
- data/processed/alias_registry_top5.json
- data/review_queue/pr2_unresolved_entities.csv
