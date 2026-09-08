# MoneySweep Spatial Binding Contract v1

Status: PROVISIONAL / NON-CERTIFYING

MoneySweep is a financial/entity producer and spatial-binding consumer. It MUST NOT synthesize or fabricate geometry to make a GIS layer appear complete.

## Binding record
Each spatial enrichment SHOULD preserve:
- money_record_id
- record_type (contract | award | project | payment | entity | asset_reference)
- raw_location_text
- source_coordinates, if supplied by the authoritative source
- candidate_canonical_ids[]
- accepted_canonical_id, nullable
- accepted_geometry_manifestation_id, nullable
- identity_cardinality (1:1 | 1:N | N:1 | N:N | 0:1 | UNRESOLVED)
- evidence_basis[]
- identity_status
- geometry_status
- review_state
- source_manifestation_sha256
- provenance

## Prohibited identity shortcuts
NAME_ONLY, NORMALIZED_NAME_ONLY, COUNT_EQUALITY, NEAREST_ONLY, PROXIMITY_ONLY, SAME_CATEGORY, and SOURCE_ABSENCE cannot establish canonical identity.

## Runtime rule
A blocked point layer remains blocked when coordinates or authoritative bindings are absent. No placeholder centroids, municipio centroids, pixel-grid positions, or nearest facilities may be promoted to project geometry.

## Ownership
MoneySweep owns financial semantics and the binding decision record. Spiderweb may provide geometry/topology services. TheHub may orchestrate discovery and expose provenance. Neither may rewrite MoneySweep financial source semantics.

## Migration gate
Existing municipality attribution may remain as jurisdictional metadata. It is not equivalent to parcel/point/line geometry. Migration is PASS only after row-conservation, cardinality, duplicate, null, and negative-regression checks close.
