# moneysweep-pr Dashboard

> **Diagnostic-only surface (ADR 0001, Phase 2).** This dashboard is a
> development and diagnostic tool for this producer only. The supported product
> surface for the PRII federation is the hub app
> (`thehub-pr/server/frontend`), which renders this producer's data alongside
> the other engines. See `thehub-pr/docs/adr/0001-federated-engines-single-hub.md`.

Local-only React dashboard for the moneysweep-pr (MoneySweep / Contracts)
module. Same federation frontend process as the others — Vite + React (JSX) +
Tailwind + shadcn/ui + react-query, Auth stripped. Data-table centric
(not geospatial), so no map.

## Run

```bash
# 1. Backend (from repo root) — thin FastAPI over the canonical_v1 CSVs, on :8000
pip install -r server/backend/requirements.txt   # fastapi, uvicorn, pandas
uvicorn server.backend.main:app --reload --port 8000

# 2. Frontend (this dir) on :5173
npm install
npm run dev
```

Open http://localhost:5173. (`VITE_API_BASE` overrides the API base; default
`http://localhost:8000`.)

## Styling

Tailwind CSS 4, through the `@tailwindcss/vite` plugin. There is no
`tailwind.config.js` or PostCSS config: the design tokens (colours, radius,
fonts) and the files Tailwind scans for class names are declared in
`src/index.css`. Browsers need Safari 16.4, Chrome 111 or Firefox 128 or newer;
the desktop app's WebView requirements are in `desktop/README.md`.

`npm run build:export` (`VITE_OFFLINE=1`) writes the single-file offline export.
Its inlining step is `scripts/inline-single-file.mjs`, covered by a unit test.

## What it shows
- **Contracts** — joined awarding/contractor names + municipality, filterable by
  agency; detail sheet per contract. *Award amounts are blank in the frozen
  Tranche A canonical set and render as "—".*
- **Entities** — 26 resolved entities, filter by type + search.
- **Relationships** — the 64 canonical edges as a labelled adjacency list
  (`Commonwealth of Puerto Rico —LOCATED_IN→ San Juan`, …).
- **Municipios** — per-municipality contract counts (recharts) + null-safe totals.

## Backend (`server/backend/main.py`)
Reads `data/canonical_v1/*.csv` with pandas (no legacy-pipeline import). Resolves
agency/contractor via `entities.csv` and municipality via `edges.csv`
(`LOCATED_IN`). Validates CSV headers at startup and fails loud on drift. CORS
allows `:5173`.

## API Keys tab — the one deliberate write path

Every other route here is read-only, matching the diagnostic-only framing
above. `/api-keys` (`server/backend/api_keys.py`) is a single, explicit
exception: it lets an operator set pipeline credentials from the browser
instead of hand-editing `.env`, backed by the same `scripts/manage_api_keys.py`
module `scripts/set_api_key.py` (CLI) uses.

What it does and doesn't do:
- It writes to this machine's local `.env` file only. `.env` stays gitignored
  and local-only, per `docs/SECRET_HANDLING_POLICY.md`.
- The pipeline (`run_all.py`) and this backend are separate process
  lifetimes — this endpoint cannot start, feed, or reach a running pipeline.
  A saved key is picked up automatically the next time the pipeline (or a
  producer script) is manually invoked, because its config loader re-reads
  `.env` from disk on every call.
- `GET /api-keys` and the UI only ever report set/not-set per key — never a
  value, matching the secret-handling policy's audit-output rules.
- Saving a key does **not** itself authorize or unfreeze anything; the
  pipeline's existing preflight and pause-lock gates are unaffected.
- Not covered here: real access control. This assumes the backend only ever
  runs on a trusted local dev machine, same as the rest of this dashboard —
  if it's ever exposed beyond localhost, this endpoint needs auth first.
