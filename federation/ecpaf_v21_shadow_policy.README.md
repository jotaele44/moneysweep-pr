# ECPAF V2.1: MoneySweep shadow-policy pin

This **read-only pilot** binds MoneySweep to the exact merged TheHub ECPAF policy revision 2.1.1. TheHub retains all federation governance authority. MoneySweep retains its financial-domain authority and all existing security, source-identity, provenance, release, and CI gates.

The pinned SHA-256 is over the raw TheHub policy bytes at commit `5df6e4ce311d8baf9e149c6f04ce7741b8ae9ea0`. The CI job checks out that immutable commit and compares both its Git object and its on-disk policy against the pin. A future TheHub policy revision requires explicit pin reconciliation rather than auto-following `main`.

A successful pin check proves **only** source identity and the expected shadow-policy semantics. It does not execute a MoneySweep financial workflow, certify readiness, import TheHub's evaluator, publish a deployment, authorize a merge, establish live producer evidence, or certify federation LOCKSTEP.

Independent review is `NOT_REQUIRED` under the owner-approved TheHub policy revision. Advisory review is optional and does not affect mandatory security, integrity, identity, provenance or authorization requirements.

The seven CLI/module/symbol candidates are explicitly classified as **internal CI governance tooling** in `.federation/gui-capabilities.extensions/ecpaf-v21-shadow-policy-pin.json`. The existing ratchet scanner remains authoritative; no discovery paths, baseline findings or mandatory GUI rules are excluded or relaxed.
