# Contract-Sweeper Dashboard

Local-only React dashboard for the Contract-Sweeper (MoneySweep / Contracts)
module. Same federation frontend process as the others — Vite + React (JSX) +
Tailwind + shadcn/ui + react-query, Base44 auth stripped. Data-table centric
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
