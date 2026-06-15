import { useHealth, useStats } from '@/lib/hooks'
import { Database, FileText, Users, Share2 } from 'lucide-react'

function Kpi({ icon: Icon, label, value }) {
  return (
    <div className="flex items-center gap-2 rounded-md border border-slate-800 bg-slate-900 px-3 py-1.5">
      <Icon className="h-4 w-4 text-slate-400" />
      <div className="leading-none">
        <div className="text-sm font-semibold text-slate-100">{value}</div>
        <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
      </div>
    </div>
  )
}

export default function StatsBar() {
  const { data: health } = useHealth()
  const { data: stats } = useStats()
  const up = health?.status === 'ok'
  const s = stats ?? {}

  return (
    <div className="flex items-center gap-2 px-4 py-2 border-b border-slate-800 bg-slate-900/60 overflow-x-auto">
      <div className="flex items-center gap-2 shrink-0">
        <span className={`inline-flex h-2.5 w-2.5 rounded-full ${up ? 'bg-emerald-400 animate-pulse' : 'bg-red-400'}`} />
        <span className="text-sm font-medium text-slate-200">Backend {up ? 'online' : 'down'}</span>
      </div>
      <div className="h-5 w-px bg-slate-800 shrink-0" />
      <Kpi icon={FileText} label="Contracts" value={s.contracts ?? '–'} />
      <Kpi icon={Users} label="Entities" value={s.entities ?? '–'} />
      <Kpi icon={Share2} label="Edges" value={s.edges ?? '–'} />
      <Kpi icon={Database} label="Municipios" value={s.municipalities ?? '–'} />
      {s.contractsWithAmount === 0 && (
        <span className="text-[11px] text-amber-300/80 shrink-0">award amounts not populated in Tranche A</span>
      )}
    </div>
  )
}
