// REST client for the moneysweep-pr FastAPI backend.
// Backend: server/backend/main.py in development; server/backend/desktop_app.py
// in the self-contained desktop build.
import snapshot from './snapshot.json' // {} in normal builds; populated for VITE_OFFLINE exports
export const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

const OFFLINE = import.meta.env.VITE_OFFLINE === '1'

export const resolveOfflineSnapshot = (path, offlineFallback = null) => {
  if (Object.prototype.hasOwnProperty.call(snapshot, path)) return snapshot[path]
  const key = path.split('?')[0]
  return Object.prototype.hasOwnProperty.call(snapshot, key) ? snapshot[key] : offlineFallback
}

async function requestJSON(path, options = {}, offlineFallback = null) {
  if (OFFLINE) {
    if ((options.method ?? 'GET') !== 'GET') {
      throw new Error('Materialization controls are unavailable in static offline exports')
    }
    return resolveOfflineSnapshot(path, offlineFallback)
  }

  const { timeout = 8000, ...fetchOptions } = options
  const res = await fetch(`${API_BASE}${path}`, {
    ...fetchOptions,
    signal: AbortSignal.timeout(timeout),
  })
  if (!res.ok) {
    let detail = ''
    try {
      const body = await res.json()
      detail = body?.detail ? `: ${body.detail}` : ''
    } catch {
      // Preserve status-only diagnostics when the backend did not return JSON.
    }
    throw new Error(`${path} → HTTP ${res.status}${detail}`)
  }
  return res.json()
}

const fetchJSON = (path, offlineFallback = null) => requestJSON(path, {}, offlineFallback)

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
  totalFederalOutflowRows: 0, derived: {}, hasData: false,
  materializedFileCount: 0, updatedAt: null,
  emptyState: 'No campaign-finance datasets are materialized in this repository checkout.',
})
export const getCampaignFinanceContributions = (f = {}) =>
  fetchJSON(`/campaign-finance/contributions${qs(f)}`, { rows: [], total: 0, limit: f.limit ?? 500, offset: f.offset ?? 0 })
export const getCampaignFinanceEntities = (f = {}) =>
  fetchJSON(`/campaign-finance/entities${qs(f)}`, [])
export const getCampaignFinanceReports = (f = {}) =>
  fetchJSON(`/campaign-finance/reports${qs(f)}`, [])

// Desktop data-plane controls. Long materialization calls get an explicit
// ten-minute client timeout; producer failures remain source-level result rows.
export const getMaterializationStatus = () =>
  requestJSON('/materialization/status', {}, null)
export const getMaterializationSources = () =>
  requestJSON('/materialization/sources', {}, [])
export const getCredentialStatus = () =>
  requestJSON('/materialization/credentials', {}, { keys: {}, allowedKeys: [], secretsReturned: false })

export const saveCredential = (keyName, value) =>
  requestJSON(`/materialization/credentials/${encodeURIComponent(keyName)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ value }),
  })

export const deleteCredential = (keyName) =>
  requestJSON(`/materialization/credentials/${encodeURIComponent(keyName)}`, { method: 'DELETE' })

export const stageOfflineFile = (sourceId, file) => {
  const body = new FormData()
  body.append('source_id', sourceId)
  body.append('file', file)
  return requestJSON('/materialization/offline/upload', {
    method: 'POST',
    body,
    timeout: 10 * 60 * 1000,
  })
}

export const materializeOfflineSource = (sourceId) =>
  requestJSON(`/materialization/offline/${encodeURIComponent(sourceId)}/run`, {
    method: 'POST',
    timeout: 10 * 60 * 1000,
  })

export const runApiMaterialization = ({ source, family = null, dryRun = false }) =>
  requestJSON('/materialization/api/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source, family, dry_run: dryRun }),
    timeout: 10 * 60 * 1000,
  })

// API-key store: local-dev-only write path (see ApiKeysPanel.jsx). Not
// available in the OFFLINE/standalone export — there is no backend to write
// to there, so the panel that calls these is hidden entirely in that build.
export const getApiKeys = () => fetchJSON('/api-keys', [])
export const setApiKey = async (name, value) => {
  const res = await fetch(`${API_BASE}/api-keys/${encodeURIComponent(name)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ value }),
    signal: AbortSignal.timeout(8000),
  })
  if (!res.ok) throw new Error(`set ${name} → HTTP ${res.status}`)
  return res.json()
}

export const getOwnershipDeepDiveStatus = () => fetchJSON('/deep-dive/ownership/status', {
  available: false,
  certificationState: 'NOT_MOUNTED',
  certifiedIssuer: 'BPOP',
  providerEquivalence: 'OPEN',
})
export const getOwnershipDeepDive = (ticker = 'BPOP') =>
  fetchJSON(`/deep-dive/ownership/${encodeURIComponent(ticker)}`, null)
