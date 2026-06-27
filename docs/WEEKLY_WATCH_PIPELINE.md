# Weekly Watch Pipeline

## Active vector

`MONEYSWEEP_PR → WATCH_SOURCE_REGISTRY → WEEKLY_INTELLIGENCE_UPDATE_PIPELINE`

## Purpose

The weekly watch layer tracks websites, official accounts, agencies, oversight bodies, municipal sources, and media outlets that can surface new public-money signals for Puerto Rico. The layer is a lead-generation and source-discovery control plane. It does not replace the canonical source registry or the materialization-readiness gate.

## Source of truth

```text
registry/watch_sources.json
```

Generated operator surfaces:

```text
reports/weekly_watch_update_plan.json
reports/weekly_watch_update_plan.md
```

Regenerate with:

```bash
python3 scripts/build_weekly_watch_update.py --strict
```

## Promotion rule

Only authoritative or authoritative-candidate records may be promoted after normal lineage, schema, and review gates pass.

Official social accounts and media sources are `informative_only`. They may create leads, aliases, and corroboration tasks, but they may not promote records alone.

## Evidence handling

| Tier | Meaning | Promotion posture |
|---|---|---|
| T1 | Primary structured or technical source | Eligible after validation |
| T2 | Official operational publication or agency notice | Eligible only when lineage and review gates pass |
| T3 | Direct observation input | Not a normal MoneySweep source |
| T4 | Social/media/contextual signal | Lead only |

## Weekly operator workflow

1. Run the weekly watch plan builder.
2. Review category queues in `reports/weekly_watch_update_plan.md`.
3. Capture changed pages, posts, notices, reports, or publications in raw/source-specific staging.
4. For each signal, assign one of these states:
   - `no_change`
   - `lead_created`
   - `corroboration_required`
   - `authoritative_record_found`
   - `defer_manual_review`
5. Promote only after corroboration and existing moneysweep-pr promotion gates pass.

## Current watch categories

- federal recovery authoritative
- territorial recovery authoritative
- territorial procurement authoritative
- legislative context
- oversight authoritative
- municipal procurement
- official social informative
- media signal

## Intended next implementation step

Add per-source fetchers for sources with stable endpoints. Keep social and media collection as lead-only until a durable archive/capture mechanism is approved.
