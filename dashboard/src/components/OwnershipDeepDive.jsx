import { useMemo, useState } from 'react'
import QueryBoundary from '@/components/QueryBoundary'
import { Table, TableHeader, TableBody, TableRow, TableCell } from '@/components/ui/table'
import { useOwnershipDeepDive, useOwnershipDeepDiveStatus } from '@/lib/hooks'
import { scrollRegion } from '@/lib/scrollRegion'

function Metric({ label, value }) {
  return (
    <div className="rounded-md border border-border bg-card/70 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="mt-1 text-lg font-semibold tabular-nums text-foreground">{value}</div>
    </div>
  )
}

function fmtPct(value) {
  if (value == null) return '—'
  return `${Number(value).toFixed(2)}%`
}

function fmtInt(value) {
  if (value == null) return '—'
  return Math.round(Number(value)).toLocaleString()
}

export default function OwnershipDeepDive() {
  const [ticker, setTicker] = useState('BPOP')
  const statusQuery = useOwnershipDeepDiveStatus()
  const deepDiveQuery = useOwnershipDeepDive(ticker)
  const payload = deepDiveQuery.data
  const latestRows = useMemo(() => payload?.latestObservations ?? [], [payload])

  return (
    <div className="flex h-full flex-col">
      <div className="ms-filter-bar flex flex-wrap items-center justify-between gap-2 border-b border-border p-2">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-foreground">Ownership &amp; Capital Deep Dive</span>
          <select
            value={ticker}
            onChange={(event) => setTicker(event.target.value)}
            aria-label="Ownership issuer"
            className="ms-filter-control h-7 rounded-md border border-input bg-background px-2 text-xs"
          >
            <option value="BPOP">BPOP — Popular, Inc. (certified)</option>
            <option value="OFG" disabled>OFG — regression only</option>
            <option value="EVTC" disabled>EVTC — regression only</option>
          </select>
        </div>
        <div className="text-[11px] text-muted-foreground">
          Provider equivalence: <span className="font-mono">{statusQuery.data?.providerEquivalence ?? 'OPEN'}</span>
        </div>
      </div>

      <QueryBoundary
        query={deepDiveQuery}
        isEmpty={(data) => !data?.observations?.length}
        emptyLabel="Certified ownership dataset is not mounted"
      >
        <div className="grid grid-cols-2 gap-2 border-b border-border p-2 md:grid-cols-6">
          <Metric label="Certification" value={payload?.certification?.state ?? '—'} />
          <Metric label="Latest period" value={payload?.latestPeriod ?? '—'} />
          <Metric label="Source rows" value={(payload?.observationCount ?? 0).toLocaleString()} />
          <Metric label="Active" value={(payload?.activeObservationCount ?? 0).toLocaleString()} />
          <Metric label="Superseded" value={(payload?.supersededObservationCount ?? 0).toLocaleString()} />
          <Metric label="8Q periods" value={payload?.certification?.requiredPeriods?.length ?? 0} />
        </div>

        <div className="grid gap-3 border-b border-border p-3 lg:grid-cols-[1fr_320px]">
          <div>
            <div className="mb-2 text-xs font-semibold text-foreground">Certification scope</div>
            <p className="text-xs leading-relaxed text-muted-foreground">
              {payload?.certification?.scope || '—'}
            </p>
            <p className="mt-2 text-[11px] text-muted-foreground">
              Whole source observations only. No cross-holder position summation. Morningstar % Total Assets remains semantically unproven and is not substituted by SEC reportable-portfolio weight.
            </p>
          </div>
          <div className="rounded-md border border-border bg-card/50 p-3 text-xs text-muted-foreground">
            <div className="font-semibold text-foreground">Real-source regression coverage</div>
            <div className="mt-2 flex justify-between"><span>OFG</span><span className="font-mono">{payload?.regressionCoverage?.OFG ?? 0}</span></div>
            <div className="mt-1 flex justify-between"><span>EVTC</span><span className="font-mono">{payload?.regressionCoverage?.EVTC ?? 0}</span></div>
            <div className="mt-2 text-[10px] uppercase tracking-wide">Regression coverage ≠ Deep Dive certification</div>
          </div>
        </div>

        <div {...scrollRegion('Ownership records')} className="ms-scroll-region min-h-0 flex-1 overflow-auto">
          <Table>
            <TableHeader className="sticky top-0 bg-card">
              <TableRow className="border-border hover:bg-transparent">
                <TableCell className="text-xs font-semibold">Holder / stable ID</TableCell>
                <TableCell className="text-xs font-semibold">As of</TableCell>
                <TableCell className="text-xs font-semibold">Filed</TableCell>
                <TableCell className="text-right text-xs font-semibold">Shares</TableCell>
                <TableCell className="text-right text-xs font-semibold">% issuer</TableCell>
                <TableCell className="text-right text-xs font-semibold">13F portfolio %</TableCell>
                <TableCell className="text-xs font-semibold">Amendment</TableCell>
                <TableCell className="text-xs font-semibold">Accession</TableCell>
              </TableRow>
            </TableHeader>
            <TableBody>
              {latestRows.map((row) => (
                <TableRow key={row.observation_id} className="border-border">
                  <TableCell className="max-w-[260px] text-xs">
                    <div className="truncate text-foreground">{row.filing_manager_name_raw || row.holder_id}</div>
                    <div className="font-mono text-[10px] text-muted-foreground">{row.holder_id}</div>
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-xs text-muted-foreground">{row.as_of_date || '—'}</TableCell>
                  <TableCell className="whitespace-nowrap text-xs text-muted-foreground">{row.report_date || '—'}</TableCell>
                  <TableCell className="text-right font-mono text-xs tabular-nums">{fmtInt(row.shares)}</TableCell>
                  <TableCell className="text-right font-mono text-xs tabular-nums">{fmtPct(row.percent_issuer_shares_computed)}</TableCell>
                  <TableCell className="text-right font-mono text-xs tabular-nums">{fmtPct(row.percent_13f_reportable_value)}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{row.amendment_status || '—'}</TableCell>
                  <TableCell className="max-w-[180px] truncate font-mono text-[10px] text-muted-foreground">{row.accession_number || '—'}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </QueryBoundary>
    </div>
  )
}
