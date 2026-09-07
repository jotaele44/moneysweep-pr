<!--
Rendered from thehub-pr/federation-templates/baseline/local-production-apps.md.
Canonical authority: TheHub ADR 0010. Generation: seven-local-apps.v1.
-->

# Seven local production apps

Each Federation repository owns an independently launchable production UI for
its domain on macOS, Windows and Linux. TheHub owns cross-producer coordination;
producer domain records remain authoritative in their owning local stores.
This supersedes ADR 0001's diagnostic-only UI direction, not its artifact-based
producer contracts or repository independence. Existing diagnostic labels remain
truthful until that capability passes its production gates.

Human capabilities must connect backend logic, API/IPC, client state and a
visible workflow. Record capabilities bidirectionally in the existing GUI
inventory. Exercise them in real-browser tests. Do not erase parity baselines,
hide unfinished controls without classification, or count syntax checks as launch
verification. Shared dependency sources must be immutable and independent of
sibling source checkouts.

Default to loopback-only local services, launcher-established sessions, protected
writes, backend-held credentials and origin/CSRF checks. Persist operation and
handoff receipts before success; expose progress, provenance, freshness, failures
and safe recovery. Optional remote services must not become implicit local-launch
requirements. Preserve source bytes and unresolved identities.

Release requires seven axes per repository (49 cells) and three platform journeys
per app (21 cells). Missing, stale, skipped, failed or unbound evidence cannot
satisfy PASS. Code proof, source proof, UI proof and hosted enforcement remain
separate. No production promotion follows from declaring this policy.
