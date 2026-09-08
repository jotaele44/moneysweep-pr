import { useEffect, useMemo, useState } from 'react'
import {
  getLeaderboardCategories,
  getLeaderboardTop,
  getLeaderboardMovers,
  getLeaderboardHistory,
  getLeaderboardSignals,
  getLeaderboardEntity,
} from '@/lib/api'

const money = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })

function StateBadge({ state }) {
  return <span className="rounded border border-border bg-muted px-2 py-0.5 text-[10px] font-medium">{state || 'UNKNOWN'}</span>
}

function DatasetCounts({ counts = {} }) {
  const rows = Object.entries(counts)
  if (!rows.length) return <p className="text-xs text-muted-foreground">No mounted records for this identity.</p>
  return <dl className="grid grid-cols-2 gap-1 text-xs">{rows.map(([key, value]) => <div key={key} className="contents"><dt className="text-muted-foreground">{key}</dt><dd className="text-right">{value}</dd></div>)}</dl>
}

export default function FinancialLeaderboards() {
  const [catalog, setCatalog] = useState(null)
  const [category, setCategory] = useState('contract_award')
  const [ranking, setRanking] = useState(null)
  const [movers, setMovers] = useState(null)
  const [history, setHistory] = useState(null)
  const [signals, setSignals] = useState(null)
  const [selectedEntityId, setSelectedEntityId] = useState(null)
  const [entityDetail, setEntityDetail] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getLeaderboardCategories().then(setCatalog).catch((err) => setError(err.message))
  }, [])

  useEffect(() => {
    let alive = true
    setLoading(true)
    setError(null)
    setSelectedEntityId(null)
    setEntityDetail(null)
    Promise.all([
      getLeaderboardTop({ category, limit: 25 }),
      getLeaderboardMovers({ category, limit: 10 }),
      getLeaderboardHistory({ category }),
      getLeaderboardSignals({ category, limit: 25 }),
    ]).then(([top, movement, snapshots, investigation]) => {
      if (!alive) return
      setRanking(top)
      setMovers(movement)
      setHistory(snapshots)
      setSignals(investigation)
    }).catch((err) => alive && setError(err.message)).finally(() => alive && setLoading(false))
    return () => { alive = false }
  }, [category])

  useEffect(() => {
    if (!selectedEntityId) return
    let alive = true
    getLeaderboardEntity(selectedEntityId)
      .then((detail) => alive && setEntityDetail(detail))
      .catch((err) => alive && setError(err.message))
    return () => { alive = false }
  }, [selectedEntityId])

  const definition = useMemo(
    () => catalog?.categories?.find((item) => item.id === category),
    [catalog, category],
  )

  return (
    <div className="h-full overflow-auto p-4">
      <div className="mx-auto max-w-7xl space-y-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold">Top financial entities</h2>
            <p className="mt-1 max-w-3xl text-xs text-muted-foreground">
              Evidence-preserving rankings by non-equivalent financial category. Stable identifiers are required; names remain display/discovery fields.
            </p>
          </div>
          <label className="text-xs text-muted-foreground">
            Category
            <select aria-label="Financial category" className="ml-2 min-h-10 rounded-md border border-border bg-background px-2 text-foreground" value={category} onChange={(event) => setCategory(event.target.value)}>
              {(catalog?.categories || []).map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
            </select>
          </label>
        </div>

        {definition && <div className="rounded-lg border border-border bg-card p-3 text-xs"><div className="flex flex-wrap items-center gap-2"><strong>{definition.metric_type}</strong><StateBadge state={ranking?.certificationState || definition.certification_state} /></div><p className="mt-2 text-muted-foreground">{ranking?.reason || definition.reason}</p></div>}
        {error && <div role="alert" className="rounded-lg border border-destructive p-3 text-sm text-destructive">{error}</div>}
        {loading && <div className="py-8 text-center text-sm text-muted-foreground">Loading ranking…</div>}

        {!loading && ranking && <div className="grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(300px,1fr)]">
          <section className="overflow-hidden rounded-lg border border-border bg-card">
            <div className="border-b border-border px-3 py-2 text-xs text-muted-foreground">Top {ranking.topN} · ties included · {ranking.metricType} · {ranking.candidateCount ?? 0} candidates</div>
            {ranking.rows?.length ? <div className="overflow-x-auto"><table className="w-full text-left text-xs"><thead className="bg-muted/50 text-muted-foreground"><tr><th className="p-2">Rank</th><th className="p-2">Entity</th><th className="p-2 text-right">Value</th><th className="p-2 text-right">Records</th><th className="p-2">Identity</th><th className="p-2">Inspect</th></tr></thead><tbody>
              {ranking.rows.map((row) => <tr key={`${row.entityId}:${row.currency}`} className="border-t border-border"><td className="p-2 font-mono">#{row.rank}</td><td className="p-2"><div className="font-medium">{row.entityDisplayName}</div><div className="font-mono text-[10px] text-muted-foreground">{row.entityId}</div></td><td className="p-2 text-right tabular-nums">{row.currency === 'USD' ? money.format(row.metricValue) : `${row.metricValue.toLocaleString()} ${row.currency}`}</td><td className="p-2 text-right tabular-nums">{row.recordCount}</td><td className="p-2"><StateBadge state={row.entityResolutionState} /></td><td className="p-2"><button type="button" className="min-h-9 rounded border border-border px-2" onClick={() => setSelectedEntityId(row.entityId)}>Inspect</button></td></tr>)}
            </tbody></table></div> : <div className="p-6 text-sm text-muted-foreground">No certifiable ranking rows for this category. Missing adapters or source manifestations remain explicit rather than becoming false zero rankings.</div>}
          </section>

          <aside className="space-y-4">
            <div className="rounded-lg border border-border bg-card p-3"><div className="flex items-center justify-between gap-2"><h3 className="text-sm font-medium">Frozen history / movers</h3><StateBadge state={movers?.movementState || 'OPEN'} /></div><p className="mt-2 text-xs text-muted-foreground">Snapshots: {history?.snapshotCount ?? 0}</p>{movers?.sourceManifestationChanged && <p className="mt-2 text-xs">Source hashes changed; movement is a dataset delta, not automatically economic activity.</p>}{movers?.rows?.length ? <div className="mt-2 space-y-1 text-xs">{movers.rows.map((row) => <div key={row.entityId} className="flex justify-between gap-2"><span>{row.entityDisplayName}</span><span className="font-mono">{row.movementState} {row.rankDelta ?? ''}</span></div>)}</div> : <p className="mt-2 text-xs text-muted-foreground">{movers?.reason || 'No comparable prior snapshot.'}</p>}</div>

            {signals?.signals?.length ? <details className="rounded-lg border border-border bg-card p-3"><summary className="cursor-pointer text-sm font-medium">Investigation signals ({signals.signalCount})</summary><div className="mt-2 space-y-2">{signals.signals.map((signal, index) => <div key={`${signal.signalType}:${signal.entityId || index}`} className="rounded border border-border p-2 text-xs"><div className="flex items-center gap-2"><strong>{signal.signalType}</strong><StateBadge state={signal.state} /></div><p className="mt-1 text-muted-foreground">{signal.interpretation}</p></div>)}</div></details> : null}

            {ranking.accounting && <div className="rounded-lg border border-border bg-card p-3 text-xs"><h3 className="text-sm font-medium">Reconciliation</h3><dl className="mt-2 grid grid-cols-2 gap-1"><dt className="text-muted-foreground">Input</dt><dd className="text-right">{ranking.accounting.inputRecords}</dd><dt className="text-muted-foreground">Retained</dt><dd className="text-right">{ranking.accounting.retainedRecords}</dd><dt className="text-muted-foreground">Excluded</dt><dd className="text-right">{ranking.accounting.excludedRecords}</dd><dt className="text-muted-foreground">Unresolved</dt><dd className="text-right">{ranking.accounting.unresolvedRecords}</dd><dt className="text-muted-foreground">Out of scope</dt><dd className="text-right">{ranking.accounting.outOfScopeRecords}</dd></dl><div className="mt-2"><StateBadge state={ranking.accounting.arithmeticClosed ? 'PASS' : 'FAIL'} /></div></div>}

            {entityDetail && <div className="rounded-lg border border-border bg-card p-3"><div className="flex flex-wrap items-center gap-2"><h3 className="text-sm font-medium">Entity neighborhood</h3><StateBadge state={entityDetail.identityState} /></div><div className="mt-2 font-mono text-[10px] break-all">{entityDetail.entityId}</div>{entityDetail.canonicalEntity?.name && <p className="mt-1 text-sm font-medium">{entityDetail.canonicalEntity.name}</p>}<div className="mt-3"><DatasetCounts counts={entityDetail.counts} /></div><div className="mt-3 rounded border border-border p-2 text-xs"><strong>Map handoff</strong><div className="mt-1"><StateBadge state={entityDetail.mapHandoff?.state} /></div>{entityDetail.mapHandoff?.municipalities?.map((muni) => <div key={muni.municipality_id} className="mt-1 text-muted-foreground">{muni.name}</div>)}</div></div>}

            {ranking.sourceManifestations?.length ? <details className="rounded-lg border border-border bg-card p-3 text-xs"><summary className="cursor-pointer text-sm font-medium">Provenance &amp; freshness</summary>{ranking.computedAt && <p className="mt-2 text-muted-foreground">Computed {ranking.computedAt}</p>}<div className="mt-2 space-y-2">{ranking.sourceManifestations.map((source) => <div key={source.path} className="rounded border border-border p-2"><div className="break-all font-medium">{source.path}</div><div className="mt-1 break-all font-mono text-[10px] text-muted-foreground">SHA256 {source.sha256}</div><div className="mt-1 text-[10px] text-muted-foreground">{source.bytes} bytes · modified {source.modifiedAt}</div></div>)}</div></details> : null}
          </aside>
        </div>}
      </div>
    </div>
  )
}
