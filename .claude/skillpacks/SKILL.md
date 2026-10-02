---
name: moneysweep-pr-unified-live-skillpack
description: "Compiled non-activating dispatch contract."
version: 1.0.1
compatibility: claude
repository: moneysweep-pr
---

# moneysweep-pr Unified Live Skillpack

Pinned base: `e14b9b8f4eb05b446a2da2072b0e247486b58e1e`.

## Execution contract

- Exact identifiers only; unknown identifiers fail closed.
- Runtime activation, automatic dispatch, polling, notifications, writes, promotion, control, merge, and release are disabled.
- Module and package hashes remain in `MANIFEST.json`.

## Capability dispatch

| Capability | Module | Status | Preserved responsibility |
|---|---|---|---|
<a id="capability-repo-state-reader"></a>| `repo-state-reader` | `repository-governance` | `preserved-active-contract` | Preserve `repo-state-reader` under `repository-governance`. |
<a id="capability-repo-identity-guard"></a>| `repo-identity-guard` | `repository-governance` | `preserved-active-contract` | Preserve `repo-identity-guard` under `repository-governance`. |
<a id="capability-branch-guard"></a>| `branch-guard` | `repository-governance` | `preserved-active-contract` | Preserve `branch-guard` under `repository-governance`. |
<a id="capability-task-scope-guard"></a>| `task-scope-guard` | `repository-governance` | `preserved-active-contract` | Preserve `task-scope-guard` under `repository-governance`. |
<a id="capability-git-action-guard"></a>| `git-action-guard` | `repository-governance` | `preserved-active-contract` | Preserve `git-action-guard` under `repository-governance`. |
<a id="capability-skill-authoring-template"></a>| `skill-authoring-template` | `skill-lifecycle` | `preserved-active-contract` | Preserve `skill-authoring-template` under `skill-lifecycle`. |
<a id="capability-skill-package-builder"></a>| `skill-package-builder` | `skill-lifecycle` | `preserved-active-contract` | Preserve `skill-package-builder` under `skill-lifecycle`. |
<a id="capability-validation-gate-runner"></a>| `validation-gate-runner` | `validation-and-recovery` | `preserved-active-contract` | Preserve `validation-gate-runner` under `validation-and-recovery`. |
<a id="capability-failure-packet-builder"></a>| `failure-packet-builder` | `validation-and-recovery` | `preserved-active-contract` | Preserve `failure-packet-builder` under `validation-and-recovery`. |
<a id="capability-delta-reporter"></a>| `delta-reporter` | `reporting-and-receipts` | `preserved-active-contract` | Preserve `delta-reporter` under `reporting-and-receipts`. |
<a id="capability-status-writer"></a>| `status-writer` | `reporting-and-receipts` | `preserved-active-contract` | Preserve `status-writer` under `reporting-and-receipts`. |
<a id="capability-foia-correspondence-manager"></a>| `foia-correspondence-manager` | `foia-operations` | `preserved-active-contract` | Preserve `foia-correspondence-manager` under `foia-operations`. |
<a id="capability-foia-request-sender"></a>| `foia-request-sender` | `foia-operations` | `preserved-active-contract` | Preserve `foia-request-sender` under `foia-operations`. |
<a id="capability-contract-sweeper-operator"></a>| `contract-sweeper-operator` | `orchestration` | `preserved-active-contract` | Preserve `contract-sweeper-operator` under `orchestration`. |
<a id="capability-moneysweep-operator"></a>| `moneysweep-operator` | `orchestration` | `preserved-active-contract` | Preserve `moneysweep-operator` under `orchestration`. |
<a id="capability-contract-sweeper-workflow"></a>| `contract-sweeper-workflow` | `orchestration` | `compatibility-alias` | Preserve `contract-sweeper-workflow` as an alias of `contract-sweeper-operator`. |
<a id="capability-moneysweep-strict-preflight"></a>| `moneysweep-strict-preflight` | `source-acquisition` | `preserved-active-contract` | Preserve `moneysweep-strict-preflight` under `source-acquisition`. |
<a id="capability-moneysweep-source-recovery"></a>| `moneysweep-source-recovery` | `source-acquisition` | `preserved-active-contract` | Preserve `moneysweep-source-recovery` under `source-acquisition`. |
<a id="capability-moneysweep-source-update-controller"></a>| `moneysweep-source-update-controller` | `source-acquisition` | `preserved-active-contract` | Preserve `moneysweep-source-update-controller` under `source-acquisition`. |
<a id="capability-moneysweep-manual-source-intake"></a>| `moneysweep-manual-source-intake` | `source-acquisition` | `preserved-active-contract` | Preserve `moneysweep-manual-source-intake` under `source-acquisition`. |
<a id="capability-moneysweep-entity-resolution"></a>| `moneysweep-entity-resolution` | `entity-and-matter-resolution` | `preserved-active-contract` | Preserve `moneysweep-entity-resolution` under `entity-and-matter-resolution`. |
<a id="capability-moneysweep-public-matter-matcher"></a>| `moneysweep-public-matter-matcher` | `entity-and-matter-resolution` | `preserved-active-contract` | Preserve `moneysweep-public-matter-matcher` under `entity-and-matter-resolution`. |
<a id="capability-moneysweep-financial-gap-audit"></a>| `moneysweep-financial-gap-audit` | `financial-gap-analysis` | `preserved-active-contract` | Preserve `moneysweep-financial-gap-audit` under `financial-gap-analysis`. |
<a id="capability-moneysweep-canonical-export"></a>| `moneysweep-canonical-export` | `export-and-promotion` | `preserved-active-contract` | Preserve `moneysweep-canonical-export` under `export-and-promotion`. |
<a id="capability-moneysweep-production-promotion"></a>| `moneysweep-production-promotion` | `export-and-promotion` | `preserved-active-contract` | Preserve `moneysweep-production-promotion` under `export-and-promotion`. |

## Required receipt fields

`capability_id`, `repository`, `pinned_base_commit`, `inputs`, `outputs`, `validation`, `limitations`, `authority`, and `next_action`.

## Non-activation boundary

This binding does not invoke repository code. Runtime adapters require separate authorization.
