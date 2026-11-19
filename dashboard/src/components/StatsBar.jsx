import { useHealth, useStats } from '@/lib/hooks'
import { Database, FileText, Share2, Users } from 'lucide-react'
import { FederationStatCard, FederationStatusBadge } from '@pr-federation/react'
import { amountsUnpopulated, AMOUNTS_NOTE } from '@/lib/cs-format'
import { scrollRegion } from '@/lib/scrollRegion'

function Kpi({ icon: Icon, label, value }) {
  return (
    <FederationStatCard
      className="ms-stat-card shrink-0"
      icon={<Icon className="h-4 w-4" />}
      label={label}
      value={value}
    />
  )
}

export default function StatsBar() {
  const { data: health, isLoading: healthLoading } = useHealth()
  const { data: stats } = useStats()
  const connecting = healthLoading && !health
  const up = health?.status === 'ok'
  const s = stats ?? {}

  const operationalState = connecting ? 'degraded' : up ? 'operational' : 'critical'
  const label = connecting ? 'Connecting…' : up ? 'Backend online' : 'Backend down'

  return (
    <div {...scrollRegion('Summary statistics')} className="panel-glass flex items-center gap-2 overflow-x-auto border-b border-border px-4 py-2">
      <FederationStatusBadge
        kind="operational"
        status={operationalState}
        className="ms-status-badge shrink-0"
        role="status"
        aria-live="polite"
      >
        {label}
      </FederationStatusBadge>
      <div className="h-5 w-px shrink-0 bg-border" aria-hidden="true" />
      <Kpi icon={FileText} label="Contracts" value={s.contracts ?? '–'} />
      <Kpi icon={Users} label="Entities" value={s.entities ?? '–'} />
      <Kpi icon={Share2} label="Edges" value={s.edges ?? '–'} />
      <Kpi icon={Database} label="Municipios" value={s.municipalities ?? '–'} />
      {amountsUnpopulated(stats) && (
        <span className="shrink-0 text-[11px] text-muted-foreground">{AMOUNTS_NOTE}</span>
      )}
    </div>
  )
}
