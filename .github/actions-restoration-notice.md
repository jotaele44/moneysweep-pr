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

- Contract Sweeper CI (core test suite)
- CodeQL
- Admin Control Plane Boundary
- Federation Compatibility
- Federation Spatial Contract
- GUI capability parity
- Source update workflows (drop-scan, freshness)
- Centinelas recovery handoff proof (added 2026-09-18)

## Exit criteria

Close this notice once at least one representative workflow on the current
`main` head allocates a real runner (`runner_id != 0`), executes its steps,
and publishes usable logs.
