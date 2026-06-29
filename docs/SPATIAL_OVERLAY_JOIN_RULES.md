# Spatial Overlay Join Rules

## Purpose

Use the shared Puerto Rico baseline grid to prevent spatial-format drift across federation repos. Domain-specific geography must resolve to `Cell_ID` before cross-repo promotion.

## Join hierarchy

| Layer | Required key | Role |
|---|---|---|
| Baseline grid | `Cell_ID` | Canonical federation spatial index |
| Civil geography | `municipality`, `barrio`, `Cell_ID` | Local place context |
| Infrastructure geography | `utility_zone`, `watershed`, `facility_id`, `Cell_ID` | Water, power, transport, and continuity context |
| Airspace geography | `airspace_sector`, `tile_id`, `Cell_ID` | FR24, SATIM, route, and airspace correlation |
| Governance geography | `permit_id`, `district`, `Cell_ID` | Permits, legislation, appropriations, and authority mapping |
| Event geography | `event_id`, `Cell_ID` | Incident, sighting, or disaster records |

## Rules

1. Do not fork the grid schema per repo.
2. Do not use municipality or barrio as the primary federation spatial key.
3. Preserve `Cell_ID`, `Row_Index`, and `Column_Index` in every derived overlay.
4. Store overlay provenance with source name, source URL or file, run timestamp, and confidence method when available.
5. Treat overlays as many-to-many when boundaries cross cell edges.
6. Use `Land_Pixel_Ratio` and `Classification` for filtering only.
7. Hub rollups should join producer outputs through `Cell_ID` first, then enrich with overlay labels.

## Promotion rule

A cross-repo spatial correlation may be promoted only when at least one record on each side resolves to a valid `Cell_ID`. If a record has coordinates but no resolved cell, it remains in staging until the spatial join is computed.
