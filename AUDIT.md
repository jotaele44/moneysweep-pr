# Fed Repos — Backend & Frontend Completion Audit

**Date:** 2026-09-21  
**Branch:** `claude/completion-audit-fed-repos-3gkse9`  
**Scope:** All 7 federated repositories under `jotaele44`

---

## Summary

| Metric | Value |
|---|---|
| Repos audited | 7 |
| Backend complete (substantial) | 5 (moneysweep, aguayluz, skywatcher, thehub + partial spiderweb) |
| Frontend complete (rich) | 4 (centinelas, skywatcher, spiderweb, thehub) |
| Critical gaps | 4 items (centinelas BE, ovnis BE, spiderweb production.py, aguayluz generated/) |
| Moneysweep test suite | 2394 passing · 51.7% coverage (gate: 44%) |

---

## Repo-by-Repo Status

### moneysweep-pr

**Backend: Substantial** — 8 API modules, 2394 tests passing, 51.7% coverage.

Files: `main.py` (9.9KB), `campaign_finance.py` (10.5KB), `case_manager_api.py` (11.1KB), `materialization.py` (11.6KB), `ownership_api.py`, `api_keys.py`, `government_changes.py`, `case_manager_auth.py`

Blockers:
- NON_PRODUCTION_DIAGNOSTIC mode active — production rebuild needed
- Archive PR-1 pending G1 approval
- PR3 dedup/entity integration not merged
- Source intake classification incomplete

**Frontend: Partial** — Vite + React. 1 page (`Dashboard.jsx`) with 15+ components, no multi-page routing.

Components present: CampaignFinance, DataSources, OwnershipDeepDive, GovernmentChanges, EntitiesTable, ContractsTable, RelationshipGraph, StatsBar, MunicipalityAggregates, QueryBoundary, ApiKeysPanel, ErrorBoundary.

Gap: All UI is collapsed into a single Dashboard page. No routing layer implemented.

---

### aguayluz-pr

**Backend: Substantial** — 7 domain API modules. main.py is 52KB (largest in fleet). water_disruption.py is 31KB.

Files: `main.py` (52KB), `water_disruption.py` (31KB), `app.py` (18KB), `cave_karst_api.py`, `environmental_exposure_api.py`, `monitoring_quality.py`, `monitoring_alert_operations.py`, `monitoring_incident_ledger.py`, `regulatory_api.py`, `water_disruption_api.py`

Gap: `generated/` directory is empty — code-generation step has not been run. Downstream consumers may lack generated schema/client artifacts.

**Frontend: N/A** — aguayluz is a backend data/GIS service consumed by thehub. No frontend expected.

---

### centinelas-pr

**Backend: Thin / Incomplete** — Only 5 Python files (8.6KB main.py). Severely underserves the 14-page frontend.

Files: `main.py` (8.6KB), `water_disruption_api.py` (6.9KB), `auth.py` (1.5KB — stub), `email_review_contract.py` (1.6KB)

Critical gaps:
- `auth.py` is 1.5KB — authentication appears to be a stub
- No backend modules for Entities, Matters, Pipeline, Signals, Sources, Handoff — 6 of 14 frontend pages have no backend coverage
- `email_review_contract.py` (1.6KB) suggests review workflow is early stage

**Frontend: Rich / Complete** — 14 pages, full API layer, component library with subdirs.

Pages: Entities, EntityDetail, Matters, MatterDetail, Monitor, Pipeline, PipelineItemDetail, Signals, SignalsTable, Sources, WaterDisruption, Handoff, Home

API layer: `appClient.js` (11KB) + `pipelineClient.js`. Component subdirs: auth, monitor/, pipeline/, lifecycle/.

---

### ovnis-pr

**Backend: Minimal** — Single `main.py` (17KB) only. No domain-specific API modules. Uses `requirements.lock` instead of `uv.lock`.

Critical gaps:
- No API modules — CaseMap (19.5KB) and SpatialToolsPanel (13.5KB) in frontend have no backend counterpart
- `requirements.lock` diverges from fleet toolchain (uv)
- No visible backend test files

**Frontend: Component-rich, page-sparse** — 1 page (`Dashboard.jsx`) despite rich spatial components.

Components: `CaseMap.jsx` (19.5KB), `SpatialToolsPanel.jsx` (13.5KB), `CaseDetail.jsx`, `CaseGrid.jsx`, `StatsPanel.jsx`, `CandidateReview.jsx`. Tests on CaseDetail, QueryState, SpatialToolsPanel.

Gap: CandidateReview → CaseDetail case workflow routing layer missing. Components are built but not wired to pages.

---

### skywatcher-pr

**Backend: Substantial** — 56KB main.py (largest in fleet), 30+ specialized modules (satim_* pipeline, aircraft/airspace intelligence, GIS).

Files: `main.py` (56KB), 15 `satim_*.py` modules, `aircraft_intelligence.py`, `gis_intelligence.py`, `aasb_airspace_bridge.py`, `ilap_airspace_bridge.py`. Specialized dirs: adsb/, fr24/, gebco/, imagery/, pipeline/, sensor_replay/.

Gap: `server/backend/console/` directory exists but is empty — `Console.jsx` frontend page has no backend counterpart.

**Frontend: Most complete individual repo** — 20 pages, full auth flow, calibration UI, spatial truth.

Pages: Aircraft, Airports, AnalysisLenses (12.4KB), Calibration (15.7KB), Console, Dashboard, ExportCenter, FR24Intake, ForgotPassword, Infrastructure, Login, ManualReview, Observations (11.4KB), Readiness, Register, ResetPassword, Routes (17.5KB), SpatialTruth (12.7KB).

Note: `federationClient.js` (9KB) is a single thin API client for a 20-page frontend — likely under-covers available endpoints.

---

### spiderweb-pr

**Backend: Partial** — `production.py` is 372 bytes (stub). No backend test files found.

Files: `main.py` (25.9KB), `martin_ingress.py` (3.8KB), `production.py` (372B — stub)

Critical gap: `production.py` is effectively empty — production entry point is a stub. Multiple requirements files (earthgpt, gebco, imagery, rag, spatial) reflect complex dependency matrix but no backend tests.

**Frontend: Sophisticated (TypeScript)** — Module-based architecture, unique TypeScript stack in fleet.

Modules: `SpatialIntelligence.tsx` (33KB), `SpatialToolsPanel.tsx` (15KB), `FinanceIntelligence.tsx` (9.5KB), `AnomalyWorkbench.tsx`, `CommandCenter.tsx`, `QueryLayer.tsx`, `InvestigationGraph.tsx`.

API: `client.ts` (12KB) with resilience tests; rag-client present. Strong test coverage (SpatialIntelligence, SpatialToolsPanel, FinanceIntelligence, ErrorBoundary, Inspector).

Note: TypeScript diverges from JSX convention used by all other repos.

---

### thehub-pr

**Backend: Most complete** — 20+ modules, full federation orchestration layer, MCP API, Docker deployment.

Files: `main_core.py` (28KB), `federation_manager_operations.py` (27KB), `federation_manager_receipts.py` (27KB), `federation_manager_transactions.py` (24KB), `federation_manager_runner.py` (22KB), `federation_manager_api.py` (21KB), `seed_federation.py` (20KB), `federation_manager_secrets.py` (17KB), `federation_manager_files.py` (17KB), `notifications.py` (15KB), `federation_manager_artifacts.py` (12KB), `federation_manager.py` (11KB), `gis_proxy.py` (7.8KB), `mcp_api.py` (4.9KB), `admin_control_plane.py` (1.9KB).

Capabilities: Docker (Dockerfile + docker-compose.yml), MCP API integration, federation seeding, repository registry/runner, secret management.

**Frontend: Most comprehensive** — 35 pages (aggregates all 6 spoke repos), 15+ component subdirectories.

Pages include: AguaYLuz, Centinelas, MoneySweep, Ovnis, Skywatcher, Spiderweb (hub views for each repo), plus Dashboard, Operations (13.3KB), OperatorSettings (18.9KB), ResearchAssistant (11.5KB), GISWorkspace (18.2KB), FederationCrossoverWorkspace, Cases, Tasks, Gates, Sources, AppCenter, ModuleReadiness.

Component dirs: audit/, cases/, crossover/, dashboard/, exports/, feed/, github/, intelligence/, layout/, manager/, notifications/, overlap/, research/, shared/, tasks/, ui/.

Manager components: `GateStatusPanel.jsx`, `RunConsole.jsx`, `SecretPresencePanel.jsx`, `OperationForm.jsx`, `RepositoryDataHealthPanel.jsx`.

---

## Priority Gaps & Action Items

| Priority | Repo | Layer | Gap |
|---|---|---|---|
| **High** | centinelas | Backend | auth.py stub; no API modules for Entities, Matters, Pipeline, Signals, Sources — 14-page frontend underserved |
| **High** | ovnis | Backend | Single main.py; CaseMap + SpatialToolsPanel have no backend; requirements.lock diverges from uv toolchain |
| **High** | spiderweb | Backend | production.py is 372-byte stub; no backend test files |
| **Medium** | aguayluz | Backend | generated/ directory empty — code-gen artifacts not produced |
| **Medium** | moneysweep | Both | NON_PRODUCTION_DIAGNOSTIC mode; Production rebuild + G1 approval + PR3 merge all pending; frontend has no routing |
| **Medium** | skywatcher | Backend | server/backend/console/ empty — Console.jsx page has no backend counterpart |
| **Medium** | ovnis | Frontend | 1 page despite rich case workflow components — routing layer missing |
| **Low** | moneysweep | Frontend | 15+ components collapsed into single Dashboard.jsx page |
| **Low** | spiderweb | Frontend | TypeScript stack diverges from JSX convention of all other repos |
| **Low** | skywatcher | Frontend | federationClient.js (9KB) thin for 20-page frontend surface |

---

## Cross-Cutting Observations

**Toolchain divergence:** 5 repos use `uv.lock` (aguayluz, centinelas, skywatcher, spiderweb, thehub). ovnis uses `requirements.lock`. moneysweep uses plain `requirements.txt` in its backend dir. Standardize on uv across all repos.

**Frontend type divergence:** 5 repos use JSX (moneysweep, centinelas, ovnis, skywatcher, thehub). spiderweb uses TypeScript. Deliberate architectural choice or drift? If drift, align spiderweb to fleet convention or migrate others.

**thehub as integration surface:** thehub has dedicated pages for all 6 spoke repos. Gaps in centinelas and ovnis backends will manifest as incomplete data in hub's Centinelas.jsx and Ovnis.jsx pages.

**Test coverage distribution:** moneysweep has the only documented coverage metric (2394 tests, 51.7%). spiderweb has the strongest frontend test suite. centinelas and ovnis have partial frontend test coverage. aguayluz and skywatcher backends have no visible test files.

---

*Audit artifact: https://claude.ai/artifact/G8dsMnxcTN8ouJaaQrULF2*
