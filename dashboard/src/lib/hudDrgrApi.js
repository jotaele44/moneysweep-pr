import { API_BASE } from './api'

async function auditRequest(method) {
  if (import.meta.env.VITE_OFFLINE === '1') {
    throw new Error('Source audits are unavailable in static offline exports')
  }
  const response = await fetch(`${API_BASE}/materialization/hud-drgr/audits`, {
    method, signal: AbortSignal.timeout(method === 'POST' ? 600000 : 8000),
  })
  if (!response.ok) {
    let detail = ''
    try { detail = (await response.json()).detail || '' } catch { /* HTTP status remains available. */ }
    throw new Error(`Audit HTTP ${response.status}${detail ? `: ${detail}` : ''}`)
  }
  const data = await response.json()
  if (method === 'GET' && !Array.isArray(data?.audits)) {
    throw new Error('Audit response is invalid; saved snapshots have not been refreshed')
  }
  return data
}

export const getHudDrgrAudits = () => auditRequest('GET')
export const createHudDrgrAudit = () => auditRequest('POST')
