// REST client for the moneysweep-pr FastAPI backend.
// Backend: server/backend/main.py  (uvicorn server.backend.main:app --port 8000)
// Reads the frozen canonical_v1 CSVs. award amounts are frequently null.
import snapshot from './snapshot.json' // {} in normal builds; populated for VITE_OFFLINE exports
export const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

// Offline export build: resolve from an embedded data snapshot instead of fetching.
// (A file:// page cannot fetch at all, so standalone exports bake the data in.)
const OFFLINE = import.meta.env.VITE_OFFLINE === '1'

async function getJSON(path, fallback = null) {
  if (OFFLINE) {
    const key = path.split('?')[0] // server-side filters degrade to the unfiltered snapshot
    return key in snapshot ? snapshot[key] : fallback
  }
  try {
    const res = await fetch(`${API_BASE}${path}`, { signal: AbortSignal.timeout(8000) })
    if (!res.ok) return fallback
    return await res.json()
  } catch {
    return fallback
  }
}

const qs = (params) => {
  const p = Object.entries(params).filter(([, v]) => v != null && v !== '')
  return p.length ? '?' + new URLSearchParams(p).toString() : ''
}

export const getHealth = () => getJSON('/health', { status: 'down', rows: {} })
export const getContracts = (f = {}) => getJSON(`/contracts${qs(f)}`, [])
export const getEntities = (f = {}) => getJSON(`/entities${qs(f)}`, [])
export const getEdges = (f = {}) => getJSON(`/edges${qs(f)}`, [])
export const getMunicipalities = () => getJSON('/municipalities', [])
export const getStats = () => getJSON('/stats', null)
