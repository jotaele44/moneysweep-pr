# Real-Time Data Acquisition Audit & Remediation Plan

**Date:** 2026-09-23
**Scope:** Every code path that performs real-time / live data acquisition in
MoneySweep, surveyed end to end from trigger to UI. No code was changed as
part of this audit — findings and a prioritized remediation plan only.

## 1. Scope & method

Three areas were surveyed independently, since "real-time data acquisition"
spans the full stack:

1. **Orchestration** — `moneysweep/update_controller/`, `moneysweep/pipeline/`,
   `moneysweep/runtime/`, and the GitHub Actions workflows that drive them.
2. **Connectors** — `moneysweep/query/adapters/`, `moneysweep/query/dispatcher.py`,
   `moneysweep/capital_control/`, `scripts/sources/`, `scripts/providers/`.
3. **Server / dashboard** — `server/backend/`, `dashboard/src/`, and the
   "live readiness" reporting under `reports/live-readiness/`.

**Terminology note:** this codebase has no continuously-running polling loop
or push channel anywhere (no `inotify`/`watchdog`, no WebSocket, no SSE). The
only genuine `while True` in the tree is page-iteration in
`moneysweep/runtime/pagination_runtime.py:37`. "Live" in MoneySweep means *a
source that is fetched from a live upstream government API on trigger*, not
*continuously streaming data*. "Live readiness" / "live freeze"
(`reports/live-readiness/`, `moneysweep/fusion/publication_gate.py:38-77`) is
a separate concept again: a batch provenance/certification gate that decides
whether data sourced live is cleared for publication — not a freshness or
runtime mechanism. Keeping these three senses of "live" distinct matters for
anyone extending this system.

## 2. System map

| Layer | Entry point | Trigger |
|---|---|---|
| Orchestration | `update_controller/cli.py` (`plan`/`run`/`scan-drops`/`ingest-drops`/`freshness`) | GitHub Actions cron (`source-update-{weekly,monthly,quarterly,yearly}.yml`, daily `source-update-drop-scan.yml` / `source-update-freshness.yml`); `workflow_dispatch` with operator confirmation for live materialization (`campaign-finance-live-materialization.yml`, `sam-opportunities-fetch.yml`, `materialize-sources.yml`); one webhook (`centinelas-intake.yml`, `repository_dispatch: centinelas-signal`) |
| Pipeline validation | `moneysweep/pipeline/{source_delivery_watch,source_delivery_handoff,source_recovery_pause_lock,scoped_unfreeze_materialization}.py` | Invoked by the orchestration layer as pipeline stages R4.9E→R4.9F→R4.9Z→R4.9G |
| Connectors | `moneysweep/query/dispatcher.py` → `moneysweep/query/adapters/*.py`; `moneysweep/capital_control/source_adapter.py`; `scripts/sources/*.py` | Called synchronously by pipeline/CLI runs; not scheduled themselves |
| Server | `server/backend/main.py` | Loads canonical CSVs once at process import; no reload-on-change |
| Dashboard | `dashboard/src/lib/hooks.js`, `dashboard/src/components/*` | React Query hooks; one 15s poll (`useHealth`), everything else fetch-once-per-mount |

End-to-end path: **GitHub Actions cron/dispatch → `update_controller` →
pipeline validation stages → `query` adapters / `capital_control` / `scripts/sources`
hit live upstream APIs → materialized to canonical CSVs → `server/backend`
serves them → dashboard fetches/polls.**

## 3. Findings by layer

Severity/effort legend: **Impact** = latency, resource waste, or data-quality
risk if left unfixed. **Effort** = rough implementation size (S/M/L).

### 3.1 Orchestration (`update_controller`, `pipeline`, `runtime`)

| # | Finding | Evidence | Impact | Effort |
|---|---|---|---|---|
| O1 | Every drop-scan re-hashes every file from scratch; no mtime/size short-circuit before sha256 | `update_controller/drop_scanner.py:45-50,98-121`, `pipeline/delivered_source_validation.py:60-67` | High — wasted I/O/CPU on every daily scan, scales with corpus size | S |
| O2 | Pipeline stages R4.9E→R4.9F→R4.9Z→R4.9G each independently re-run full `validate_candidate` (sha256 + row_count + column parse) on the same candidate files instead of threading forward the prior stage's result | `source_delivery_watch.py:159-217` → `scoped_unfreeze_materialization.py:205-224` | High — same file validated up to 4x per pipeline run | M |
| O3 | `discover_candidate_paths` does `rglob("*")` over the dropzone/staging tree once **per checklist row** instead of indexing the tree once | `pipeline/delivered_source_validation.py:113-155` | Med — O(rows × tree size) directory walk | S |
| O4 | `row_count` reads whole CSVs line-by-line, called repeatedly across pipeline stages for the same file | `pipeline/delivered_source_validation.py:70-82` | Med | S |
| O5 | Concurrency capped at `--workers` default of **4** via `ThreadPoolExecutor`, not scaled to the number of per-hostname lanes, against 100+ sources | `update_controller/cli.py:294-297,377-381`, `scheduler.py:12-26` | High — orchestration wall-clock time bottleneck | S |
| O6 | `CircuitBreaker` is implemented (`runtime/retry_runtime.py:80-150`) but never wired into `runtime/base_downloader.py`'s `http_get_json`/`http_post_json` (only plain `with_retry` is used) | `runtime/base_downloader.py:140-214` | Med — chronically-failing endpoints get hammered fresh every cron cycle instead of tripping open | S |
| O7 | Dependency-triggered re-planning re-evaluates *every* dependency-triggered source rather than only direct children of the sources that actually changed | `update_controller/cli.py:315-321` | Med | M |
| O8 | No run-level lock — nothing prevents two concurrent `run` invocations (e.g. overlapping manual dispatch during a scheduled run) from racing on the same state file | `update_controller/` (absence of any lock primitive) | Med — correctness risk, not just performance | S |

### 3.2 Connectors (`query/adapters`, `query/dispatcher`, `capital_control`, `scripts/sources`)

| # | Finding | Evidence | Impact | Effort |
|---|---|---|---|---|
| C1 | `dispatcher.query()` iterates `source_ids` **strictly sequentially** — no thread pool or asyncio anywhere in the fetch path | `moneysweep/query/dispatcher.py:150-154` | **Highest single lever** — querying N sources takes the sum of N latencies | M |
| C2 | Every adapter hand-rolls a near-identical `_get_session()` (lazy `requests.Session()`, same headers, same `timeout=60`) instead of a shared base | `query/adapters/usaspending.py:176-183`, `sam.py:52-64`, `fec.py:43-56`, `cms_socrata.py:55-70` | Med — ~30-40 duplicated lines × 6+ files; harder to fix bugs once | M |
| C3 | Caching (`query/cache.py:32-46`) is TTL-only (7-365 days by cadence); no conditional requests (ETag / If-Modified-Since), so a cache miss always refetches the entire result set rather than a delta | `moneysweep/query/cache.py` | Med — unnecessary full refetches on expiry | M |
| C4 | Retry policy is applied inconsistently: LDA fetcher reimplements its own exponential backoff instead of reusing the shared policy | `scripts/sources/fetch_lda_gov.py:235-244` vs `runtime/retry_runtime.py` | Low/Med — maintenance risk, inconsistent behavior under failure | S |
| C5 | SAM's documented 1000 req/day limit is never enforced in code | `query/adapters/sam.py:8` (docstring only) | Med — risk of hitting upstream rate limit with no local guard | S |
| C6 | `cms_socrata.py` silently swallows per-resource exceptions with no logging — a failed year-shard vanishes with zero trace | `query/adapters/cms_socrata.py:100-104` | Med — silent data loss, hard to debug | S |
| C7 | No structured logging of fetch latency, page count, or byte volume in any adapter; only `_LOG.exception` on total failure at the dispatcher level | `query/dispatcher.py:100-101` | Med — no observability into which sources are slow/expensive | S |
| C8 | `MAX_PAGES` caps (100-200) truncate silently with no signal to the caller that results are partial | `usaspending.py:34`, `fec.py:26`, `cms_socrata.py:31` | Med — data-quality risk (looks complete, isn't) | S |
| C9 | 9+ agency-narrowed `usaspending` adapter subclasses each independently paginate the same upstream endpoint with only filter differences, instead of one broader query split client-side | `query/adapters/usaspending.py:33-34,164-221` | Low/Med — redundant upstream calls | M |
| C10 | LDA fetcher's cursor-based pagination has no `MAX_PAGES`-style cap and is known to hit HTTP 400 on deep pages for ~2M-row tables | `scripts/sources/fetch_lda_gov.py:280-297` (comment at 285-289) | Med — known failure mode already observed | M |
| — | **Positive reference implementation:** the SEC EDGAR client already does this right — real rate limiting (5 req/s, `_rate_limit`), `Retry-After` header honoring, content-type/size/sha256 verification, idempotent freeze-to-disk | `capital_control/source_adapter.py:180-424` | — | — (template to generalize from) |

### 3.3 Server / dashboard

| # | Finding | Evidence | Impact | Effort |
|---|---|---|---|---|
| S1 | Backend loads all canonical CSVs once at process import with no reload-on-change and no reload endpoint — "live" dashboard data is a frozen snapshot until the process restarts | `server/backend/main.py:64-79` | High — directly contradicts the "live" framing users see in the UI | M |
| S2 | `useHealth()` polls every 15s, mounted permanently outside the tab system, with no `document.hidden` pause and no `refetchOnWindowFocus` (explicitly disabled) — polls forever even when backgrounded | `dashboard/src/lib/hooks.js:11`, `StatsBar.jsx:18`, `Dashboard.jsx:54`, `query-client.js` | Low/Med — wasted requests, but payload is small | S |
| S3 | `useHealth()` and `useStats()` both read overlapping row-count data from the same server-side in-memory dict but are fetched and cached independently, never reconciled | `hooks.js:11-12` vs `server/backend/main.py:110-115,250` | Low — duplicate round-trip, potential to silently drift | S |
| S4 | `DataSources.jsx` bypasses React Query entirely (raw `useEffect`+`useState`), fetches once on mount, and gives no progress feedback during long-running (up to 10 min) materialization jobs beyond a manual "Refresh" button | `DataSources.jsx:79-91`, `api.js:112-124` | Med — poor UX for the one workflow that's actually long-running/live | M |
| S5 | `ProgramTimeline.jsx` ("tailored program activity timeline") is fully hardcoded static data, sitting inside the "Activity" tab next to genuinely live-fetched components — it can never reflect real backend state | `Dashboard.jsx:16-22` | Med — data/UI honesty issue, likely to mislead users or future maintainers | S/M (depends on whether it's wired to real data or just relabeled) |

## 4. Prioritized remediation plan

Ordered by impact-to-effort ratio. Each item is scoped to be independently
implementable without re-discovery.

### P1 — do first (high impact, contained blast radius)

1. **Parallelize `dispatcher.query()` (C1).** Replace the sequential `for sid
   in source_ids` loop (`query/dispatcher.py:150-154`) with a bounded thread
   pool (adapters are I/O-bound `requests` calls, so threads suffice —
   asyncio would require rewriting every adapter). Cap concurrency to avoid
   overwhelming any single upstream host; group by hostname the same way
   `scheduler.py` already does for orchestration lanes, so parallelism
   doesn't create the rate-limit collisions the lane design was built to
   avoid. Expected benefit: total dispatch time drops from sum-of-latencies
   to max-of-latencies (per lane).
2. **Add mtime/size short-circuit before re-hashing (O1)** in
   `drop_scanner.py` and `delivered_source_validation.py`: skip sha256 when
   a file's `(mtime, size)` matches the last recorded scan. Store the last
   known `(mtime, size, sha256)` triple per path.
3. **Thread validation results forward across pipeline stages (O2)**:
   have R4.9E's `validate_candidate` output (keyed by path + content hash)
   passed to R4.9F/R4.9Z/R4.9G instead of each stage re-deriving it, as long
   as the file hasn't changed since (reuse the O1 short-circuit key).
4. **Scale orchestration concurrency to lane count (O5)**: make
   `--workers` default to (or auto-detect) the number of distinct hostname
   lanes rather than a flat 4, since lanes already exist specifically to
   parallelize safely across hosts.

### P2 — next (moderate effort, meaningful reliability/maintainability win)

5. **Extract a shared HTTP base for adapters (C2)**, generalizing the
   pattern `_USAspendingBase` already proves works: one `_get_session()`,
   shared headers, shared `timeout` config (make it centrally configurable
   rather than hardcoded `60` in each file), and a shared `_get`/`_post`
   wrapper in `query/adapters/base.py`. Migrate `usaspending`, `sam`, `fec`,
   `cms_socrata` onto it.
6. **Generalize the SEC adapter's rate-limiting/backoff pattern (C5, C2's
   follow-on)**: lift `_rate_limit` / `Retry-After` handling from
   `capital_control/source_adapter.py:214-254` into the shared base so
   SAM's documented-but-unenforced 1000 req/day limit (and any other
   adapter's documented limit) gets real enforcement.
7. **Wire `CircuitBreaker` into `base_downloader.py` (O6)** so a
   chronically-failing endpoint trips open instead of being retried fresh
   every cron cycle.
8. **Pause `useHealth()` polling on `document.hidden` and reconcile with
   `useStats()` (S2, S3)**: gate the 15s interval on page visibility, and
   either merge the two hooks or have one derive from the other's cached
   result to remove the duplicate round-trip.

### P3 — after P1/P2 (targeted fixes, lower urgency)

9. **Add progress polling to `DataSources.jsx` (S4)** for long-running
   materialization jobs — a `refetchInterval` while a job is in-flight, or
   a status endpoint the client can poll, so users get feedback without
   manually clicking Refresh.
10. **Resolve the `ProgramTimeline.jsx` data/UI mismatch (S5)**: either wire
    it to real backend activity data, or relabel it explicitly as a static
    roadmap so it stops looking like live program telemetry.
11. **Replace LDA fetcher's ad hoc backoff with the shared retry policy
    (C4)**, and add a `MAX_PAGES`-equivalent cap with a clear truncation
    signal to the caller (also apply this signal to C8's existing silent
    truncation in `usaspending`/`fec`/`cms_socrata`).
12. **Stop the silent exception-swallow in `cms_socrata.py:100-104` (C6)**
    — log the resource/year that failed rather than `except Exception:
    continue`.
13. **Add structured fetch-latency/byte-volume/page-count logging to
    adapters (C7)** so slow or expensive sources are visible without
    reading code.

### P4 — lower priority / larger refactors

14. **Add a run-level lock in `update_controller` (O8)** to prevent
    overlapping concurrent `run` invocations from racing on shared state.
15. **Narrow dependency-triggered re-planning to direct children only (O7)**
    instead of re-evaluating every dependency-triggered source.
16. **Consolidate the 9+ agency-narrowed `usaspending` adapters (C9)** into
    one broader query with client-side agency splitting, reducing redundant
    upstream calls.
17. **Introduce conditional requests where the upstream API supports them
    (C3)** (ETag / If-Modified-Since) so a cache-TTL expiry triggers a
    cheap freshness check before a full refetch, not a full refetch itself.
18. **Give the server a reload-on-change path (S1)** — either a watch on the
    canonical CSV directory or an explicit "reload" trigger surfaced in the
    dashboard, so the dashboard's "live" framing matches reality without
    requiring a process restart. Note: per this repo's `AGENTS.md` GUI
    parity rule, any such backend capability must also get a GUI surface
    (status/freshness indicator, not just an internal endpoint) and a
    `.federation/gui-capabilities.json` update when implemented.

## 5. Cross-cutting note on "live" terminology

Nothing found here is a functional bug in the "live readiness" gate itself —
`moneysweep/fusion/publication_gate.py` and the `reports/live-readiness/`
certification receipts do what they're meant to do (provenance/publication
safety). The risk is purely one of naming: a reader encountering "live" in
three different contexts (live upstream source, live readiness/freeze gate,
and the dashboard's real-time framing) without this audit could reasonably
assume there's a continuous data pipeline, when in fact every acquisition is
trigger-based and the dashboard serves a point-in-time snapshot. Recommend
documenting this distinction near the top of `moneysweep/update_controller/`
and `server/backend/main.py` for future contributors.

## 6. Appendix — file:line reference index

- `moneysweep/update_controller/cli.py:294-297,315-321,377-381`
- `moneysweep/update_controller/drop_scanner.py:45-50,98-121`
- `moneysweep/update_controller/scheduler.py:12-26`
- `moneysweep/pipeline/delivered_source_validation.py:60-67,70-82,113-155`
- `moneysweep/pipeline/source_delivery_watch.py:159-217`
- `moneysweep/pipeline/scoped_unfreeze_materialization.py:205-224`
- `moneysweep/runtime/base_downloader.py:140-214`
- `moneysweep/runtime/retry_runtime.py:80-150`
- `moneysweep/runtime/pagination_runtime.py:24-46`
- `moneysweep/query/dispatcher.py:100-101,150-154`
- `moneysweep/query/cache.py:32-46`
- `moneysweep/query/adapters/usaspending.py:33-34,164-221,176-183`
- `moneysweep/query/adapters/sam.py:8,52-64`
- `moneysweep/query/adapters/fec.py:26,43-56`
- `moneysweep/query/adapters/cms_socrata.py:31,55-70,100-104`
- `moneysweep/capital_control/source_adapter.py:180-424,214-254`
- `scripts/sources/fetch_lda_gov.py:235-244,280-297`
- `server/backend/main.py:64-79,110-115,250`
- `dashboard/src/lib/hooks.js:11-12`
- `dashboard/src/lib/query-client.js`
- `dashboard/src/components/StatsBar.jsx:18`
- `dashboard/src/pages/Dashboard.jsx:16-22,54`
- `dashboard/src/components/DataSources.jsx:79-91`
- `dashboard/src/lib/api.js:112-124`
- `moneysweep/fusion/publication_gate.py:38-77`
