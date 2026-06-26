// moneysweep-pr display helpers.

export function fmtMoney(v) {
  if (v == null) return '—'
  try {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(v)
  } catch {
    return String(v)
  }
}

const ENTITY_TONE = {
  agency: 'bg-sky-500/15 text-sky-300 border-sky-500/30',
  utility: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
  firm: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
  fund: 'bg-violet-500/15 text-violet-300 border-violet-500/30',
  person: 'bg-rose-500/15 text-rose-300 border-rose-500/30',
}
export const entityTone = (t) => ENTITY_TONE[t] ?? 'bg-slate-500/15 text-slate-300 border-slate-500/30'

const STATUS_TONE = {
  active: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
  flagged: 'bg-red-500/15 text-red-300 border-red-500/30',
  amended: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
  executed: 'bg-sky-500/15 text-sky-300 border-sky-500/30',
}
export const statusTone = (s) => STATUS_TONE[s] ?? 'bg-slate-500/15 text-slate-300 border-slate-500/30'

const EDGE_TONE = {
  LOCATED_IN: 'text-teal-300',
  AWARDED_TO: 'text-amber-300',
  CONTROLS: 'text-rose-300',
  AFFILIATED_WITH: 'text-violet-300',
  SUBSIDIARY_OF: 'text-sky-300',
}
export const edgeTone = (t) => EDGE_TONE[t] ?? 'text-slate-300'
