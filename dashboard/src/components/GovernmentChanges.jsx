import { Badge } from '@/components/ui/badge'
import { Table, TableHeader, TableBody, TableRow, TableCell } from '@/components/ui/table'
import QueryBoundary from '@/components/QueryBoundary'
import GovernmentChangeCandidates from '@/components/GovernmentChangeCandidates'
import { useGovernmentChanges, useGovernmentChangeSummary } from '@/lib/hooks'
import { scrollRegion } from '@/lib/scrollRegion'

export default function GovernmentChanges() {
  const query = useGovernmentChanges()
  const summary = useGovernmentChangeSummary()
  const rows = query.data ?? []
  const totals = summary.data

  return (
    <div className="flex h-full flex-col" data-testid="government-change-monitor">
      <div className="ms-filter-bar flex flex-wrap items-center gap-3 p-2 text-xs text-muted-foreground">
        <span className="font-medium text-foreground">Government organization change monitor</span>
        <span>Events: {totals?.events ?? '—'}</span>
        <span>Candidates: {totals?.candidates ?? '—'}</span>
        <span>Alerts: {totals?.alerts ?? '—'}</span>
        <span>Binding: {totals?.binding ?? '—'}</span>
        {totals && !totals.ledgerPresent && <Badge variant="outline">event ledger not materialized</Badge>}
        {totals && !totals.candidateLedgerPresent && <Badge variant="outline">candidate ledger not materialized</Badge>}
      </div>
      <div {...scrollRegion('Government changes')} className="ms-scroll-region min-h-0 flex-1 overflow-auto">
        <QueryBoundary query={query} isEmpty={(data) => !data?.length} emptyLabel="No adjudicated government change events are materialized. Absence here is not evidence of no organizational change.">
          <Table>
            <TableHeader className="sticky top-0 bg-card">
              <TableRow className="border-border hover:bg-transparent">
                <TableCell>Entity</TableCell>
                <TableCell>Change</TableCell>
                <TableCell>Effective</TableCell>
                <TableCell>State</TableCell>
                <TableCell>Severity</TableCell>
                <TableCell>Impact</TableCell>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.change_event_id} className="border-border">
                  <TableCell className="font-mono text-xs">{row.affected_entity_id}</TableCell>
                  <TableCell className="text-xs">{row.event_type}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{row.effective_date || 'pending'}</TableCell>
                  <TableCell className="text-xs">{row.derived.timeline_state}</TableCell>
                  <TableCell><Badge variant="outline">{row.derived.severity}</Badge></TableCell>
                  <TableCell className="max-w-[360px] text-xs text-muted-foreground">
                    {row.derived.invalidation_scopes.join(', ')}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </QueryBoundary>
        <GovernmentChangeCandidates />
      </div>
    </div>
  )
}
