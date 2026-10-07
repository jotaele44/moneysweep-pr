# Federation code review — 2026-10-07

Review base: `bbe4c022f2874c3c4492c0bc2ad727d1fe8109bf`.

Scope: repository API and data boundaries, federation metadata, existing regression tests, GUI capability gates, and shared infrastructure where applicable. This is a targeted review with automated validation, not a claim that every possible defect has been eliminated.

## Changes

- **P1:** Infinite amounts could fail contracts API JSON serialization. Parse finite amounts or null.
- **P2:** ASG resumable acquisition and identity-audit infrastructure lacked capability bindings. Classify these existing producer integrity controls as internal and retain their existing leaderboard product surface.
- **P2:** ASG coverage YAML, generated JSON, and reports disagreed. Use the dated committed 2026-10-06 materialization receipt (1,431 unique control numbers; no duplicate/missing control numbers), regenerate metadata in a clean checkout, and bind the regression assertion to the receipt. This does not certify the whole source, vendor identities, or a new live manifestation.

## Validation

Validation results are recorded in the pull request description. Regression cases include invalid inputs and preservation of normal behavior. GUI parity baselines were not regenerated.

The review uses isolated local checkouts and synthetic regression fixtures. Existing frozen-source receipts retain their original scope and date; they do not establish live source freshness. Shared-package consumer pins remain immutable until a separate release/pin update.
