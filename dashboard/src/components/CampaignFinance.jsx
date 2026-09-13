import { useMemo, useState } from 'react'
import { Input } from '@/components/ui/input'
import { Table, TableHeader, TableBody, TableRow, TableCell } from '@/components/ui/table'
import QueryBoundary from '@/components/QueryBoundary'
import {
  useCampaignFinanceContributions,
  useCampaignFinanceEntities,
  useCampaignFinanceReports,
  useCampaignFinanceSummary,
} from '@/lib/hooks'
import { fmtMoney } from '@/lib/cs-format'

function Metric({ label, value }) {
  return (
    <div className="rounded-md border border-border bg-card/70 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="mt-1 text-lg font-semibold tabular-nums text-foreground">{value}</div>
    </div>
  )
}

function ContributionsTable({ query }) {
  const payload = query.data ?? { rows: [], total: 0 }
  return (
    <QueryBoundary query={query} isEmpty={(data) => !data?.rows?.length} emptyLabel="No campaign-finance contributions are materialized">
      <Table>
        <TableHeader className="sticky top-0 bg-card">
          <TableRow className="border-border hover:bg-transparent">
            <TableCell className="text-xs font-semibold">Date</TableCell>
            <TableCell className="text-xs font-semibold">Donor</TableCell>
            <TableCell className="text-xs font-semibold">Recipient</TableCell>
            <TableCell className="text-xs font-semibold">Source</TableCell>
            <TableCell className="text-xs font-semibold">Party</TableCell>
            <TableCell className="text-right text-xs font-semibold">Amount</TableCell>
          </TableRow>
        </TableHeader>
        <TableBody>
          {(payload.rows ?? []).map((row, index) => (
            <TableRow key={`${row.source}-${row.date}-${row.donorName}-${index}`} className="border-border">
              <TableCell className="whitespace-nowrap text-xs text-muted-foreground">{row.date || '—'}</TableCell>
              <TableCell className="max-w-[220px] truncate text-xs text-foreground">{row.donorName || '—'}</TableCell>
              <TableCell className="max-w-[250px] truncate text-xs text-muted-foreground/80">{row.recipientName || '—'}</TableCell>
              <TableCell className="text-xs uppercase text-muted-foreground">{row.source}</TableCell>
              <TableCell className="text-xs text-muted-foreground">{row.party || '—'}</TableCell>
              <TableCell className="text-right font-mono text-xs tabular-nums">{fmtMoney(row.amount)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </QueryBoundary>
  )
}

function EntitiesTable({ query }) {
  const rows = query.data ?? []
  return (
    <QueryBoundary query={query} isEmpty={(data) => !data?.length} emptyLabel="No campaign-finance entities are materialized">
      <Table>
        <TableHeader className="sticky top-0 bg-card">
          <TableRow className="border-border hover:bg-transparent">
            <TableCell className="text-xs font-semibold">Type</TableCell>
            <TableCell className="text-xs font-semibold">Name</TableCell>
            <TableCell className="text-xs font-semibold">Party / resolved type</TableCell>
            <TableCell className="text-xs font-semibold">Office</TableCell>
            <TableCell className="text-right text-xs font-semibold">Amount</TableCell>
            <TableCell className="text-xs font-semibold">Review</TableCell>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, index) => (
            <TableRow key={`${row.entityType}-${row.entityId}-${index}`} className="border-border">
              <TableCell className="text-xs uppercase text-muted-foreground">{row.entityType}</TableCell>
              <TableCell className="max-w-[300px] truncate text-xs text-foreground">{row.name || '—'}</TableCell>
              <TableCell className="text-xs text-muted-foreground">{row.party || row.resolvedType || '—'}</TableCell>
              <TableCell className="text-xs text-muted-foreground">{row.office || '—'}</TableCell>
              <TableCell className="text-right font-mono text-xs tabular-nums">{row.amount == null ? '—' : fmtMoney(row.amount)}</TableCell>
              <TableCell className="text-xs text-muted-foreground">{row.reviewStatus || '—'}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </QueryBoundary>
  )
}

function ReportsTable({ query }) {
  const rows = query.data ?? []
  return (
    <QueryBoundary query={query} isEmpty={(data) => !data?.length} emptyLabel="No OCE campaign-finance reports are materialized">
      <Table>
        <TableHeader className="sticky top-0 bg-card">
          <TableRow className="border-border hover:bg-transparent">
            <TableCell className="text-xs font-semibold">Filed</TableCell>
            <TableCell className="text-xs font-semibold">Committee</TableCell>
            <TableCell className="text-xs font-semibold">Report</TableCell>
            <TableCell className="text-xs font-semibold">Type</TableCell>
            <TableCell className="text-xs font-semibold">Period</TableCell>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, index) => (
            <TableRow key={`${row.report_number}-${index}`} className="border-border">
              <TableCell className="whitespace-nowrap text-xs text-muted-foreground">{row.filed_at || '—'}</TableCell>
              <TableCell className="max-w-[300px] truncate text-xs text-foreground">{row.committee_name || '—'}</TableCell>
              <TableCell className="text-xs text-muted-foreground">{row.report_number || '—'}</TableCell>
              <TableCell className="text-xs text-muted-foreground">{row.report_type || '—'}</TableCell>
              <TableCell className="max-w-[220px] truncate text-xs text-muted-foreground">{row.reporting_period || '—'}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </QueryBoundary>
  )
}

export default function CampaignFinance() {
  const [view, setView] = useState('contributions')
  const [source, setSource] = useState('all')
  const [search, setSearch] = useState('')
  const contributionFilters = useMemo(() => ({ source, q: search, limit: 1000 }), [source, search])
  const entityFilters = useMemo(() => ({ q: search, limit: 1000 }), [search])
  const reportFilters = useMemo(() => ({ q: search, limit: 1000 }), [search])
  const summaryQuery = useCampaignFinanceSummary()
  const contributionsQuery = useCampaignFinanceContributions(contributionFilters)
  const entitiesQuery = useCampaignFinanceEntities(entityFilters)
  const reportsQuery = useCampaignFinanceReports(reportFilters)
  const summary = summaryQuery.data ?? { sources: [], derived: {} }
  const contributionPayload = contributionsQuery.data ?? { rows: [], total: 0 }
  const sourceCounts = Object.fromEntries((summary.sources ?? []).map((item) => [item.source, item.rows]))

  return (
    <div className="flex h-full flex-col">
      <div className="grid grid-cols-2 gap-2 border-b border-border p-2 md:grid-cols-5">
        <Metric label="Contribution rows" value={(summary.totalContributionRows ?? 0).toLocaleString()} />
        <Metric label="Signed amount" value={fmtMoney(summary.totalContributionAmount)} />
        <Metric label="FEC" value={(sourceCounts.fec ?? 0).toLocaleString()} />
        <Metric label="CEE + OCE" value={((sourceCounts.cee ?? 0) + (sourceCounts.oce ?? 0)).toLocaleString()} />
        <Metric label="Federal outflows" value={(summary.totalFederalOutflowRows ?? 0).toLocaleString()} />
      </div>
      {!summaryQuery.isPending && !summary.hasData && (
        <div role="status" className="border-b border-border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
          {summary.emptyState || 'No campaign-finance datasets are materialized.'}
        </div>
      )}
      {summary.hasData && summary.updatedAt && (
        <div className="border-b border-border px-3 py-1 text-[10px] text-muted-foreground">
          Latest materialized file: {new Date(summary.updatedAt).toLocaleString()}
        </div>
      )}

      <div className="ms-filter-bar flex flex-wrap items-center justify-between gap-2 p-2">
        <div className="flex items-center gap-2">
          <select
            value={view}
            onChange={(event) => setView(event.target.value)}
            aria-label="Campaign-finance view"
            className="ms-filter-control h-7 rounded-md border border-input bg-background px-2 text-xs"
          >
            <option value="contributions">Contributions</option>
            <option value="entities">Candidates, committees & recipients</option>
            <option value="reports">OCE reports</option>
          </select>
          {view === 'contributions' && (
            <select
              value={source}
              onChange={(event) => setSource(event.target.value)}
              aria-label="Campaign-finance source"
              className="ms-filter-control h-7 rounded-md border border-input bg-background px-2 text-xs"
            >
              <option value="all">All sources</option>
              <option value="fec">FEC</option>
              <option value="cee">CEE</option>
              <option value="oce">OCE</option>
            </select>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">
            {view === 'contributions' ? `${contributionPayload.total?.toLocaleString?.() ?? 0} matches` : ''}
          </span>
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={view === 'reports' ? 'Filter committee…' : 'Filter name…'}
            aria-label="Filter campaign-finance records"
            className="ms-filter-control h-7 w-[230px] bg-background text-xs"
          />
        </div>
      </div>

      <div className="ms-scroll-region min-h-0 flex-1 overflow-auto">
        {view === 'contributions' && <ContributionsTable query={contributionsQuery} />}
        {view === 'entities' && <EntitiesTable query={entitiesQuery} />}
        {view === 'reports' && <ReportsTable query={reportsQuery} />}
      </div>
    </div>
  )
}
