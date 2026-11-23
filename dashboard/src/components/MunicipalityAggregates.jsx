import { useMemo } from 'react'
import { useMunicipalities } from '@/lib/hooks'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts'
import QueryBoundary from '@/components/QueryBoundary'
import StatsDistributions from '@/components/StatsDistributions'
import { fmtMoney } from '@/lib/cs-format'
import { hslVar, chartColor } from '@/lib/theme'
import { scrollRegion } from '@/lib/scrollRegion'

// Per-municipality contract counts (award totals are null in Tranche A, so the
// chart plots counts; totals appear in the table when populated).
export default function MunicipalityAggregates() {
  const query = useMunicipalities()
  const munis = query.data ?? []
  const data = useMemo(() => munis.map((m) => ({ name: m.name, contracts: m.contracts, total: m.total })), [munis])
  const c = useMemo(() => ({
    grid: hslVar('--border'),
    axis: hslVar('--muted-foreground'),
    bar: chartColor(0),
    popover: hslVar('--popover'),
    border: hslVar('--border'),
  }), [])

  return (
    <div {...scrollRegion('Municipality aggregates')} className="flex h-full flex-col gap-3 overflow-auto p-3">
      <StatsDistributions />
      <QueryBoundary query={query} isEmpty={(d) => !d?.length} emptyLabel="No municipio data">
        <div className="rounded-md border border-border bg-card p-3">
          <h4 className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">Contracts per municipio</h4>
          <div className="h-48">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data} margin={{ top: 4, right: 8, bottom: 4, left: -16 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={c.grid} />
                <XAxis dataKey="name" tick={{ fill: c.axis, fontSize: 11 }} />
                <YAxis allowDecimals={false} tick={{ fill: c.axis, fontSize: 11 }} />
                <Tooltip
                  cursor={{ fill: c.grid, opacity: 0.3 }}
                  contentStyle={{ background: c.popover, border: `1px solid ${c.border}`, borderRadius: 6, fontSize: 12 }}
                />
                <Bar dataKey="contracts" fill={c.bar} radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="divide-y divide-border rounded-md border border-border bg-card">
          {munis.map((m) => (
            <div key={m.municipalityId ?? m.name} className="flex items-center justify-between px-3 py-2">
              <span className="text-sm text-foreground">{m.name}</span>
              <span className="text-xs text-muted-foreground">{m.contracts} contracts · {fmtMoney(m.total)}</span>
            </div>
          ))}
        </div>
      </QueryBoundary>
    </div>
  )
}
