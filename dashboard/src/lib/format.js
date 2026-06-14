// Shared display helpers (badge tones, map colors, dates). Reused by MapView
// and the side panels. Hex values feed MapLibre paint; class strings feed
// shadcn <Badge>.

// Anomaly severity band. Seed uses hi / med / lo; tolerate high/medium/low too.
const BAND = {
  hi: { label: 'High', hex: '#ef4444', badge: 'bg-red-500/15 text-red-300 border-red-500/30' },
  med: { label: 'Medium', hex: '#f59e0b', badge: 'bg-amber-500/15 text-amber-300 border-amber-500/30' },
  lo: { label: 'Low', hex: '#10b981', badge: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' },
}
const BAND_ALIAS = { high: 'hi', medium: 'med', low: 'lo' }

export function bandMeta(band) {
  const key = BAND_ALIAS[band] ?? band
  return BAND[key] ?? { label: band ?? '—', hex: '#64748b', badge: 'bg-slate-500/15 text-slate-300 border-slate-500/30' }
}
export const bandHex = (band) => bandMeta(band).hex

// Evidence tier T1 (strongest) → T4 (weakest).
const TIER = {
  T1: 'bg-sky-500/15 text-sky-300 border-sky-500/30',
  T2: 'bg-indigo-500/15 text-indigo-300 border-indigo-500/30',
  T3: 'bg-violet-500/15 text-violet-300 border-violet-500/30',
  T4: 'bg-slate-500/15 text-slate-300 border-slate-500/30',
}
export const tierBadge = (tier) => TIER[tier] ?? TIER.T4

// Source status.
export function statusMeta(status) {
  switch (status) {
    case 'online': return { dot: 'bg-emerald-400', label: 'Online' }
    case 'partial': return { dot: 'bg-amber-400', label: 'Partial' }
    case 'offline': return { dot: 'bg-red-400', label: 'Offline' }
    default: return { dot: 'bg-slate-500', label: status ?? 'Unknown' }
  }
}

export function fmtDate(s) {
  if (!s) return '—'
  // Accept ISO date or datetime; show YYYY-MM-DD HH:MM when time present.
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return s
  const hasTime = /\d{2}:\d{2}/.test(s)
  return hasTime ? d.toISOString().slice(0, 16).replace('T', ' ') : s.slice(0, 10)
}
