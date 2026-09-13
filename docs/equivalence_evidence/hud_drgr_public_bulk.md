# HUD DRGR equivalence evidence status

Registered source: `hud_drgr_authorized`.

Candidate: HUD DRGR public/bulk data surfaces.

The registered source contract expects both `data/staging/processed/hud_drgr_activities.csv` and `data/staging/processed/hud_drgr_projects.csv` from the authorized DRGR export ingestion path. Public/bulk DRGR availability does not by itself prove that the candidate has the same Puerto Rico program scope, temporal universe, row universe, field mapping, selection semantics, or aggregation semantics.

No candidate bytes and no complete comparison manifest are mounted in the current certification scope.

Certification consequence: public/bulk DRGR data MUST NOT silently substitute for `hud_drgr_authorized`. State remains UNPROVEN pending an operator export or a complete byte-backed equivalence proof.
