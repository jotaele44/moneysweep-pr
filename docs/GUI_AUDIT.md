# GUI Audit — moneysweep-pr Dashboard

Audit date: 2026-08-23
Scope: `dashboard/` (React/Vite SPA) and its desktop launcher entry points.

## Overview

`moneysweep-pr` is the public-money intelligence **producer** for the PRII
(Puerto Rico Integrated Intelligence) federation — it acquires, normalizes,
and cross-links public procurement, entity, campaign-finance, and government
change data into the frozen `data/canonical_v1/*.csv` corpus. When this audit
was written, the repo's README described **the `dashboard/` app audited here as
a diagnostic-only surface for this producer** (ADR 0001, Phase 2), with the
separate `thehub-pr` hub app as the federation's supported product surface.
That framing matters for reading this audit: it treats the dashboard as a
read-only, single-producer inspection tool. The framing has since been
superseded by thehub-pr ADR 0014, under which the dashboard is this producer's
own complete application; the README now says so.

**Tech stack**
- React 19 + Vite 6, `react-router-dom` v7 (BrowserRouter in normal builds,
  HashRouter for offline single-file exports), TanStack Query v5 for data
  fetching/caching.
- UI kit: a local shadcn/ui-style primitive set (`dashboard/src/components/ui`)
  wrapping Radix primitives (`@radix-ui/react-select`, `-dialog`, `-tabs`,
  `-slot`), plus a shared cross-federation component package
  `@pr-federation/react` (status badges, stat cards, buttons, empty/error/
  loading/offline/stale state panels) pulled from a GitHub release tarball.
  `recharts` renders the one chart (municipio bar chart).
- Backend: a thin read-only FastAPI service (`server/backend/main.py`) that
  loads `data/canonical_v1/*.csv` with pandas at import time and serves
  joined, camelCase JSON — no database, no write endpoints. Two routers are
  mounted: `campaign_finance.py` (reads optional `data/staging/processed/*`
  CSVs, degrading to empty results when absent) and `government_changes.py`
  (reads optional `data/derived/*.json` ledgers, same degrade-to-empty
  pattern).
- A second, entirely separate FastAPI app (`server/backend/case_manager_app.py`
  / `case_manager_api.py`, the "Case Manager Phase 1" service) exists in the
  same directory but is **not mounted into the dashboard's backend and has no
  client in `dashboard/src`** — it is not reachable from any control in this
  GUI and is out of scope for this audit.

**Entry points**
- **Dev**: `cd dashboard && npm install && npm run dev` → Vite dev server
  (default `http://localhost:5173`, hard-coded in `vite.config.js` because it
  must match the backend's default CORS allow-list). Backend:
  `uvicorn server.backend.main:app --reload --port 8000` from the repo root.
- **Desktop launcher** (see full detail below): double-click
  `PRII-MONEYSWEEP.command` (macOS), `PRII-MONEYSWEEP.bat` (Windows), or
  `PRII-MONEYSWEEP.sh` (Linux), or open `PRII-MONEYSWEEP.app` on macOS. First
  run builds a private `.venv` and the Vite production bundle (needs
  internet + Node once); later runs start instantly and work offline, opening
  a native window that same-origin-serves the API and the built SPA from one
  local port.
- **Offline single-file export**: `npm run build:export` (`VITE_OFFLINE=1`)
  snapshots the API responses into `src/lib/snapshot.json` and produces a
  single self-contained `index.html` under `dashboard/export-standalone/`
  that opens via `file://` with no server at all (HashRouter, data baked in).

**Routing.** The SPA has exactly one real route (`/`, rendering
`pages/Dashboard.jsx`) plus a catch-all `*` → `lib/PageNotFound.jsx`. All
"pages" a user actually navigates between are **tabs inside `Dashboard.jsx`**,
switched via a `?tab=` query-string param (`contracts | entities |
government-changes | graph | municipios | campaign-finance`), which is why
this audit — per the task brief — treats `dashboard/src/components` as the
real page-equivalent surface.

## How this audit was done

1. **Static catalog** — every file under `dashboard/src/pages` and
   `dashboard/src/components` was read in full, tracing each interactive
   element to its handler and, from there, to the exact API call, client-side
   filter/sort logic, or navigation it performs.
2. **Live verification** — `npm install` (network via the environment proxy),
   `pip install fastapi 'uvicorn[standard]' pandas`, then both the FastAPI
   backend (`uvicorn server.backend.main:app`, serving the repo's real,
   already-populated `data/canonical_v1/*.csv` — 3 contracts, 30 entities, 66
   edges, 78 municipalities; no external API keys required) and the Vite dev
   server were started locally. Chromium at `/opt/pw-browsers/chromium` was
   driven via `playwright-core` (no `playwright install` run) to load the
   dashboard and click/type/select through every control, watching the
   browser console for errors. **Zero console errors or page errors were
   observed across the entire run.** Both processes were stopped afterward.
   - Note: this container runs several sibling repos' audits concurrently.
     The Vite/FastAPI default ports (5173/8000) were transiently occupied by
     other repos' dev servers; the frontend was restarted with
     `--port 34173 --strictPort` and the backend with an explicit
     `MONEYSWEEP_CORS_ORIGINS` override so it would accept that origin — both
     verified by title/content inspection to be genuinely moneysweep-pr's own
     servers before any clicking began.
3. Controls that need data this environment doesn't have (populated
   `data/staging/processed/*` campaign-finance CSVs, a materialized
   `data/derived/government_organization_change_events.json` with events, a
   simulated offline/error/stale network condition, or the native desktop
   `pywebview` runtime) are marked **static-only**, with the specific
   dependency named.

---

## 1. Global navigation — `pages/Dashboard.jsx`

The shell: brand header (static), `StatsBar` (live KPIs, not interactive —
see below), and a 6-way tab strip. Tab state lives in the URL (`useSearchParams`),
so it's shareable/bookmarkable and survives reload.

| Element | Type | Label | Handler/Behavior | Verified | Notes |
|---|---|---|---|---|---|
| Contracts tab | Tab trigger | "Contracts" | `setTab('contracts')` → `params.set('tab', 'contracts')`, replaces URL, mounts `<ContractsTable/>` | Live | Default tab |
| Entities tab | Tab trigger | "Entities" | same mechanism, `tab=entities` → `<EntitiesTable/>` | Live | |
| Gov Changes tab | Tab trigger | "Gov Changes" | `tab=government-changes` → `<GovernmentChanges/>` | Live | |
| Relationships tab | Tab trigger | "Relationships" | `tab=graph` → `<RelationshipGraph/>` | Live | |
| Municipios tab | Tab trigger | "Municipios" | `tab=municipios` → `<MunicipalityAggregates/>` | Live | |
| Campaign Finance tab | Tab trigger | "Campaign Finance" | `tab=campaign-finance` → `<CampaignFinance/>` | Live | |

`StatsBar` (`components/StatsBar.jsx`) shows a live backend-status badge
(`useHealth()`, polls `GET /health` every 15s) and four read-only KPI cards
(Contracts/Entities/Edges/Municipios from `GET /stats`). No clickable
elements — confirmed by code (no `onClick`/`onChange` anywhere in the file)
and by DOM inspection during the live run.

---

## 2. Contracts — `components/ContractsTable.jsx`

Backed by `useContracts()` → `GET /contracts` (optional `municipality`,
`agency`, `status`, `fiscal_year` query params exist server-side, but this
view only ever sends a bare request and filters client-side).

| Element | Type | Label | Handler/Behavior | Verified | Notes |
|---|---|---|---|---|---|
| Agency filter | Text input | "Filter by awarding agency…" | `setAgency(e.target.value)`; `useMemo` filters the fetched contracts client-side by case-insensitive substring match on `awardingName` | Live | Typed "Highways" → 3 rows → 1 row; cleared → back to 3 |
| Sort: Contract | Column header | "Contract" | `sort('contractNumber')` (via `useSortable`) toggles asc/desc client-side sort | Live (pattern) | Same `SortHead`/`useSortable` mechanism verified live on the Amount column below |
| Sort: Awarding | Column header | "Awarding" | `sort('awardingName')` | Live (pattern) | |
| Sort: Contractor | Column header | "Contractor" | `sort('contractorName')` | Live (pattern) | |
| Sort: Municipio | Column header | "Municipio" | `sort('municipality')` | Live (pattern) | |
| Sort: Amount | Column header | "Amount" | `sort('awardAmount')`; null-safe numeric compare, nulls sort last | Live | Clicked once → `aria-sort="ascending"`; clicked again → `"descending"` |
| Sort: Status | Column header | "Status" | `sort('status')` | Live (pattern) | |
| Row select | Table row (`role="button"`, focusable) | any contract row | `onClick`/Enter/Space → `setOpen(c)` opens a detail `Sheet` | Live | Verified both mouse click and keyboard `Enter` |
| Sheet close | Icon button (X, sr-only "Close") | — | Radix `SheetPrimitive.Close` → `onOpenChange(false)` → `setOpen(null)` | Live | Verified via the equivalent `Escape` dismissal path (same `onOpenChange` callback) |
| Clear filters | Button | "Clear filters" | Shown only in the filtered-empty state; `onResetFilters={() => setAgency('')}` | Live | Filtered to a nonsense agency string → empty state + button appeared; click reset the input and restored all 3 rows |
| Retry / Refresh | Button (shared `QueryBoundary` state banner/panel) | "Retry" (offline/error) or "Refresh" (stale) | `refetch()` on the `useContracts` query → re-`GET /contracts` | Static-only: requires simulated offline/backend-error/stale-data conditions | Component logic read in full (`components/QueryBoundary.jsx`); not exercised live since the backend stayed healthy throughout |

The detail Sheet renders `contractNumber`/`contractId`, awarding entity,
contractor, municipality, formatted award amount, start→end period, fiscal
year, and confidence — all read-only display, no further controls inside it.

---

## 3. Entities — `components/EntitiesTable.jsx`

Backed by `useEntities()` → `GET /entities`.

| Element | Type | Label | Handler/Behavior | Verified | Notes |
|---|---|---|---|---|---|
| Search | Text input | "Search entities…" | `setQ(e.target.value)`; client-side substring match on `name` | Live | Searched "Puerto Rico Electric" → 30 rows → 1 row; cleared → 30 |
| Type filter | Select (Radix, via `TypeFilterSelect`) | entity type ("all" + distinct `entityType` values found in the fetched data) | `setType(value)`; client-side exact-match filter | Live | Opened, options were `all/agency/utility/fund/firm`; selecting `agency` cut 30 rows → 16 |
| Sort: Name | Column header | "Name" | `sort('name')` | Live (pattern) | Same `SortHead` mechanism verified live on Contracts' Amount column |
| Sort: Type | Column header | "Type" | `sort('entityType')` | Live (pattern) | |
| Sort: Jurisdiction | Column header | "Jurisdiction" | `sort('jurisdiction')` | Live (pattern) | |
| Sort: Conf. | Column header | "Conf." | `sort('confidence')`, right-aligned numeric | Live (pattern) | |
| Row select | Table row | any entity row | `setOpen(e)` opens detail `Sheet` | Live | |
| Sheet close | Icon button (X) | — | Same Radix `Close` pattern as Contracts | Live | |
| Clear filters | Button | "Clear filters" | `resetFilters()` → `setType('all'); setQ('')` | Live | Searched a nonsense string → filtered-empty state + button; click cleared the search box |
| Retry / Refresh | `QueryBoundary` state action | "Retry" / "Refresh" | `refetch()` → re-`GET /entities` | Static-only: requires simulated offline/error/stale | |

Detail Sheet: type badge, name, entity ID, jurisdiction, parent entity ID,
confidence, notes — read-only.

---

## 4. Gov Changes — `components/GovernmentChanges.jsx` + `components/GovernmentChangeCandidates.jsx`

Backed by `useGovernmentChanges()` → `GET /government-changes`,
`useGovernmentChangeSummary()` → `GET /government-changes/summary`, and (in
the nested candidates component) `useGovernmentChangeCandidates()` →
`GET /government-changes/candidates`. This is the one view with **no
filter/sort/row-click controls** — both tables are plain read-only rows; the
summary line (`Events / Candidates / Alerts / Binding` counts + "ledger not
materialized" badges) is static text, not interactive.

| Element | Type | Label | Handler/Behavior | Verified | Notes |
|---|---|---|---|---|---|
| Retry (events table) | `QueryBoundary` state action | "Retry" | `refetch()` → re-`GET /government-changes` | Static-only: requires simulated error, or a real populated ledger to reach the non-empty path | `data/derived/government_organization_change_events.json` exists but evaluates to 0 rows in this environment; live run confirmed the exact empty-state copy ("No adjudicated government change events are materialized…") renders correctly |
| Retry (candidates table) | `QueryBoundary` state action | "Retry" | `refetch()` → re-`GET /government-changes/candidates` | Static-only | Same empty-ledger situation (`data/staging/processed/government_organization_change_candidates.json` absent) |

---

## 5. Relationships — `components/RelationshipGraph.jsx`

Backed by `useEdges()` → `GET /edges`. Despite the tab label "Relationships"
and the "graph" internal name, this view renders a **list**, not a node/edge
diagram — each relationship is a horizontal row (`source → edgeType/amount →
target`), not a canvas.

| Element | Type | Label | Handler/Behavior | Verified | Notes |
|---|---|---|---|---|---|
| Edge type filter | Select (Radix, via `TypeFilterSelect`) | edge type ("all" + distinct `edgeType` values) | `setType(value)`; client-side exact-match filter | Live | Options: `all, LOCATED_IN, ADVISES, OWNS_OR_CONTROLS, HOLDS_ROLE_IN, HOLDS_DEBT, FUNDED_BY, RECEIVES_CONTRACT, LOBBIES_FOR`; selecting `LOCATED_IN` cut 66 rows → 21 |
| Clear filters | Button | "Clear filters" | Filtered-empty state; `onResetFilters={() => setType('all')}` | Static-only: every edge type present in the sample data has ≥1 match, so the 0-result state wasn't reachable with real data | Mechanism identical to (and already live-verified on) Contracts/Entities |
| Retry / Refresh | `QueryBoundary` state action | "Retry" / "Refresh" | `refetch()` → re-`GET /edges` | Static-only | |

---

## 6. Municipios — `components/MunicipalityAggregates.jsx` + `components/StatsDistributions.jsx`

Backed by `useMunicipalities()` → `GET /municipalities` (aggregated
contract-count-per-municipio; only municipios with ≥1 linked contract appear
— 1 row in this sample, "San Juan", since all 3 seed contracts resolve there)
and `useStats()` → `GET /stats` (for the distribution bars). **No
filter/sort/search controls** in this view.

| Element | Type | Label | Handler/Behavior | Verified | Notes |
|---|---|---|---|---|---|
| Bar chart tooltip | Recharts `<Tooltip>` (hover) | — | Hovering a bar shows the exact contract count for that municipio | Static-only: chart render confirmed (`.recharts-wrapper` present, correct data), but the hover/hit-test interaction itself wasn't exercised in the headless run | |
| Retry / Refresh | `QueryBoundary` state action | "Retry" / "Refresh" | `refetch()` → re-`GET /municipalities` | Static-only | |

`StatsDistributions` (Contracts by status / by service / Entities by type
proportion bars) has no interactive elements at all — pure `useStats()`
display.

---

## 7. Campaign Finance — `components/CampaignFinance.jsx`

Backed by `useCampaignFinanceSummary()` → `GET /campaign-finance/summary`,
and, depending on which sub-view is selected, `useCampaignFinanceContributions`
→ `GET /campaign-finance/contributions`, `useCampaignFinanceEntities` →
`GET /campaign-finance/entities`, or `useCampaignFinanceReports` →
`GET /campaign-finance/reports`. All four endpoints read from
`data/staging/processed/*.csv`, which are **absent in this environment**, so
every metric and table renders its correct, honest zero/empty state rather
than throwing — a good sign for the "PRODUCTION_PLACEHOLDER_OR_MOCK" concern
called out in the repo's own `docs/GUI_CAPABILITY_PARITY.md`.

| Element | Type | Label | Handler/Behavior | Verified | Notes |
|---|---|---|---|---|---|
| View select | Native `<select>` | "Campaign-finance view" | `setView(value)`: `contributions` / `entities` / `reports` — swaps which of the three sub-tables renders | Live | Cycled through all three options |
| Source select | Native `<select>` (only rendered when `view === 'contributions'`) | "Campaign-finance source" | `setSource(value)`: `all` / `fec` / `cee` / `oce` → passed as the `source` query param to `GET /campaign-finance/contributions` | Live | Selected "FEC" |
| Filter input | Text input | "Filter committee…" (reports view) or "Filter name…" (contributions/entities) | `setSearch(value)` → passed as `q` to whichever sub-view's query is active | Live | Typed "test", no errors, request fired with `q=test` |
| Retry (Contributions) | `QueryBoundary` state action | "Retry" | `refetch()` → re-`GET /campaign-finance/contributions` | Static-only: needs populated staging CSVs to reach non-empty path | |
| Retry (Entities) | `QueryBoundary` state action | "Retry" | `refetch()` → re-`GET /campaign-finance/entities` | Static-only | |
| Retry (Reports) | `QueryBoundary` state action | "Retry" | `refetch()` → re-`GET /campaign-finance/reports` | Static-only | |

The four summary metric tiles (Contribution rows, Signed amount, FEC,
CEE+OCE, Federal outflows) are static display, not interactive.

---

## 8. Not Found — `lib/PageNotFound.jsx`

Reached at any unmatched route (e.g. `/some-nonexistent-route`); no auth
lookup (auth was stripped from this build per the file's own comment).

| Element | Type | Label | Handler/Behavior | Verified | Notes |
|---|---|---|---|---|---|
| Go Home | Button | "Go Home" | `navigate('/')` (React Router) → returns to the Dashboard | Live | Navigated to a bogus route, confirmed the 404 heading, clicked the button, confirmed the URL returned to `/` |

## 9. App-level crash guard — `components/ErrorBoundary.jsx`

Wraps the whole `<App/>` tree in `main.jsx`. Only renders in place of the
real UI if a descendant component throws during render.

| Element | Type | Label | Handler/Behavior | Verified | Notes |
|---|---|---|---|---|---|
| Try again | Button | "Try again" | `this.setState({ error: null })` clears the caught error and re-renders children | Static-only: requires deliberately forcing a render-time exception, not attempted against the live app | Code-reviewed only |

---

## Desktop Launcher

Entry points at the repo root: `PRII-MONEYSWEEP.command` (macOS),
`PRII-MONEYSWEEP.sh` (Linux), `PRII-MONEYSWEEP.bat` (Windows), and the
double-clickable `PRII-MONEYSWEEP.app` bundle (macOS Finder). All four are
thin, self-locating shims around the same two Python entry points; the
`desktop/` folder itself is a **shared federation template** — only
`desktop/config.py` (app title `"MoneySweep"`, FastAPI import path
`server.backend.main:app`, frontend dir `dashboard/`, health path `/health`)
differs per repo. The actual launcher logic lives in the shared
`thehub-pr/packages/prii_desktop` package, imported by `desktop/launch.py`
and `desktop/app_server.py` as thin re-export shims.

**What happens when a user runs one:**

1. **`.sh`/`.command`/`.bat`** — `cd` to the repo root, run
   `python3 desktop/setup.py --ensure`, then exec
   `.venv/bin/python desktop/launch.py`. `setup.py` is idempotent (marker
   file `desktop/.setup-complete`): first run creates a private `.venv`,
   `pip install`s `server/backend/requirements.txt` +
   `requirements-desktop.txt`, then `npm ci`/`npm install` + `npm run build`
   inside `dashboard/` (with `VITE_API_BASE=""` so the built SPA calls
   same-origin). Needs internet + Node once; later runs skip straight to
   launch and work fully offline (map basemap tiles are the one exception —
   those still need a connection).
   - **`.app`** (`Contents/MacOS/PRII-MONEYSWEEP`) does the same, plus:
     resolves the repo root relative to its own bundle location, detects and
     names macOS Gatekeeper's "App Translocation" failure mode (quarantined
     `.app` run from a read-only temp copy, so `desktop/setup.py` can't be
     found next to it) with a specific fix-it dialog pointing at
     `Fix-Gatekeeper.command`, restores `PATH` entries Finder strips
     (`/opt/homebrew/bin`, `/usr/local/bin`) so `python3`/`npm` resolve, and
     logs setup output to a tmp file it can point users at on failure.
2. **`desktop/launch.py main()`** calls the shared `prii_desktop.launch()`:
   - Checks a per-app lock file (state dir under the OS's application-support
     path) for an already-running instance; if one is alive and healthy, it
     just opens the browser to that instance's URL instead of starting a
     second one.
   - Picks a free localhost TCP port, starts `uvicorn` on it in a background
     thread serving `make_desktop_app(config)` — the repo's real FastAPI app
     (`server/backend/main:app`) with the built `dashboard/dist` SPA attached
     as same-origin static files + SPA-fallback routing (so client routes
     that share a path with an API route still resolve correctly on a hard
     refresh, via an `Accept: text/html` check).
   - Opens a native `pywebview` window (falls back to the system default
     browser if pywebview is unavailable) showing a branded "Starting…"
     splash until `GET /health` responds 200, then loads the real app URL.
   - Flags: `--no-window` (serve only, print URL, block on Ctrl+C —
     headless/server mode), `--browser` (skip the native window, open the
     default browser instead), `--route PATH` (open on a specific client
     route), `--setup`/`--repair` (force-open the native Setup &
     Diagnostics center), `--smoke` (start, wait for health, exit 0/2 — used
     by CI).
   - Inside the native window, `prii_desktop/appserver.py` injects a small
     fixed bottom-right gear button (⚙, `aria-label="Open MoneySweep Setup &
     Diagnostics"`) into the served `index.html` whenever
     `window.pywebview.api` is present. This button — and the "Choose
     Folder…", "Save & Open App", "Repair Configuration", "Back to App", and
     "Run Diagnostics" buttons of the native Setup & Diagnostics page it
     opens (`prii_desktop/setup_center.py`) — is **shared federation launcher
     chrome, not part of `dashboard/src`**, so it's static-only for this
     audit: it never renders in a plain browser/dev-server session (only
     inside the pywebview desktop shell), and exercising it live would mean
     driving the pywebview runtime rather than a browser, which was out of
     scope here.
3. **`Fix-Gatekeeper.command`** (repo root, referenced by the `.app`'s error
   dialog) is a separate one-off helper that runs
   `xattr -dr com.apple.quarantine` on the app bundle to clear macOS's
   quarantine flag — not part of the normal launch path, only invoked when
   Gatekeeper blocks the first open.

None of the desktop-launcher code paths were live-driven in this audit (no
`pywebview`/native-window runtime available in this container); they are
documented from a full read of `desktop/launch.py`, `desktop/app_server.py`,
`desktop/config.py`, `desktop/setup.py`, `desktop/README.md`, all four root
launcher scripts, and the shared `prii_desktop` package
(`launcher.py`, `appserver.py`, `setup_center.py`) in `thehub-pr`.

---

## Summary

- **Pages/views audited:** 9 — the 6 dashboard tabs (Contracts, Entities, Gov
  Changes, Relationships, Municipios, Campaign Finance), plus the global tab
  navigation shell, the 404 Not Found route, and the app-level ErrorBoundary
  crash guard.
- **Total interactive elements cataloged:** 42 (within `dashboard/src`;
  desktop-launcher chrome is documented separately above and not included in
  this count since it isn't part of `dashboard/src` and never renders in a
  browser session).
  - Contracts: 11 · Entities: 10 · Gov Changes: 2 · Relationships: 3 ·
    Municipios: 2 · Campaign Finance: 6 · Global nav: 6 · Not Found: 1 ·
    ErrorBoundary: 1
- **Verified live vs. static-only:** 29 live-verified (either directly
  clicked/typed/selected, or a repeated instance of a component whose
  mechanism was directly exercised elsewhere in the same run) · 13
  static-only (all `QueryBoundary` retry/refresh actions that need a
  simulated offline/error/stale condition; the Recharts hover tooltip; the
  ErrorBoundary "Try again" button, which needs a forced render-time throw;
  and the Relationships "Clear filters" button, whose 0-result state wasn't
  reachable because every edge type in the sample data has ≥1 match).
- **Broken / dead controls found: none.** Every control's handler resolves
  to real, working behavior — a real API call, a real client-side
  filter/sort, or a real navigation — and the live Playwright run produced
  **zero console errors or page errors** across every tab, every filter/sort/
  select interaction, both detail sheets, the 404 route, and the recovery
  path back to `/`. The only "empty" states encountered (Gov Changes,
  Campaign Finance) are the app's own honest empty-data messaging for
  optional datasets that simply aren't materialized in this environment
  (`data/staging/processed/*`, `data/derived/government_organization_change_events.json`)
  — not bugs, and exactly the behavior the app's code says it should have.
