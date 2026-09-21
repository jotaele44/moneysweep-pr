# GitHub Actions Restoration Notice

**Date:** 2026-09-19  
**Status:** RESTORED

## Summary

GitHub Actions runners were unavailable from approximately 2026-09-06 through
2026-09-19. Workflows triggered during that window completed as `failure`
immediately with `runner_id: 0`, `steps: []`, and no usable logs.

## Affected window

Commits merged while Actions was unavailable used local verification in place
of CI. These commits now need to be re-verified against live runners.

## Required re-runs

The following workflow classes should be re-run on the current `main` head
now that runners are assigned:

- CI / validate
- Source update drop-scan (scheduled)
- Freshness check (scheduled)
- GUI capability parity (scheduled)
- CodeQL analysis

## Exit criteria

Close this notice once at least one representative workflow on the current
`main` head allocates a real runner (`runner_id != 0`), executes its steps,
and publishes usable logs.
