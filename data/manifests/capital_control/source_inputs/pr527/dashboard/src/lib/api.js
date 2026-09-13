// REST client for the moneysweep-pr FastAPI backend.
// Backend: server/backend/main.py  (uvicorn server.backend.main:app --port 8000)
import snapshot from './snapshot.json' // {} in normal builds; populated for VITE_OFFLINE exports
export const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

const OFFLINE = import.meta.env.VITE_OFFLINE === '1'

export const resolveOfflineSnapshot = (path, offlineFallback = null) => {
  if (Object.prototype.hasOwnProperty.call(snapshot, path)) return snapshot[path]
  const key = path.split('?')[0]
  return Object.prototype.hasOwnProperty.call(snapshot, key) ? snapshot[key] : offlineFallback
}

async function fetchJSON(path, offlineFallback = null) {
  if (OFFLINE) return resolveOfflineSnapshot(path, offlineFallback)
  const res = await fetch(`${API_BASE}${path}`, { signal: AbortSignal.timeout(8000) })
  if (!res.ok) throw new Error(`${path} → HTTP ${res.status}`)
  return res.json()
}

const qs = (params) => {
  const p = Object.entries(params).filter(([, v]) => v != null && v !== '')
  return p.length ? '?' + new URLSearchParams(p).toString() : ''
}

export const getHealth = async () => {
  try {
    return await fetchJSON('/health', { status: 'down', rows: {} })
  } catch {
    return { status: 'down', rows: {} }
  }
}
export const getContracts = (f = {}) => fetchJSON(`/contracts${qs(f)}`, [])
export const getEntities = (f = {}) => fetchJSON(`/entities${qs(f)}`, [])
export const getEdges = (f = {}) => fetchJSON(`/edges${qs(f)}`, [])
export const getMunicipalities = () => fetchJSON('/municipalities', [])
export const getStats = () => fetchJSON('/stats', null)
export const getGovernmentChanges = (f = {}) => fetchJSON(`/government-changes${qs(f)}`, [])
export const getGovernmentChangeCandidates = (f = {}) =>
  fetchJSON(`/government-changes/candidates${qs(f)}`, [])
export const getGovernmentChangeSummary = () => fetchJSON('/government-changes/summary', {
  events: 0, candidates: 0, alerts: 0, binding: 0,
  bySeverity: { S0: 0, S1: 0, S2: 0, S3: 0, S4: 0 },
  ledgerPresent: false, candidateLedgerPresent: false,
})

export const getCampaignFinanceSummary = () => fetchJSON('/campaign-finance/summary', {
  sources: [], totalContributionRows: 0, totalContributionAmount: 0,
  totalFederalOutflowRows: 0, derived: {},
})
export const getCampaignFinanceContributions = (f = {}) =>
  fetchJSON(`/campaign-finance/contributions${qs(f)}`, { rows: [], total: 0, limit: f.limit ?? 500, offset: f.offset ?? 0 })
export const getCampaignFinanceEntities = (f = {}) =>
  fetchJSON(`/campaign-finance/entities${qs(f)}`, [])
export const getCampaignFinanceReports = (f = {}) =>
  fetchJSON(`/campaign-finance/reports${qs(f)}`, [])

export const getOwnershipDeepDiveStatus = () => fetchJSON('/deep-dive/ownership/status', {
  available: false,
  certificationState: 'NOT_MOUNTED',
  certifiedIssuer: 'BPOP',
  providerEquivalence: 'OPEN',
})
export const getOwnershipDeepDive = (ticker = 'BPOP') =>
  fetchJSON(`/deep-dive/ownership/${encodeURIComponent(ticker)}`, null)
