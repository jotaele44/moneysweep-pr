import { useMunicipalities } from '@/lib/hooks'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts'
import { fmtMoney } from '@/lib/cs-format'

// Per-municipality contract counts (award totals are null in Tranche A, so the
// chart plots counts; totals appear in the table when populated).
export default function MunicipalityAggregates() {
  const { data: munis = [] } = useMunicipalities()
  const data = munis.map((m) => ({ name: m.name, contracts: m.contracts, total: m.total }))

  return (
    <div className="flex flex-col h-full p-3 gap-3 overflow-auto">
      <div className="rounded-md border border-slate-800 bg-slate-900 p-3">
        <h4 className="text-xs uppercase tracking-wide text-slate-500 mb-2">Contracts per municipio</h4>
        <div className="h-48">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 4, right: 8, bottom: 4, left: -16 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="name" tick={{ fill: '#94a3b8', fontSize: 11 }} />
              <YAxis allowDecimals={false} tick={{ fill: '#94a3b8', fontSize: 11 }} />
              <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 6, fontSize: 12 }} />
              <Bar dataKey="contracts" fill="#38bdf8" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="rounded-md border border-slate-800 bg-slate-900 divide-y divide-slate-800">
        {munis.map((m) => (
          <div key={m.municipalityId ?? m.name} className="flex items-center justify-between px-3 py-2">
            <span className="text-sm text-slate-200">{m.name}</span>
            <span className="text-xs text-slate-400">{m.contracts} contracts · {fmtMoney(m.total)}</span>
          </div>
        ))}
        {munis.length === 0 && <p className="text-center text-sm text-slate-500 py-8">No data</p>}
      </div>
    </div>
  )
}
