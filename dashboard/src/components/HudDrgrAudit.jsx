import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { getHudDrgrAudits, createHudDrgrAudit } from '@/lib/hudDrgrApi'

export default function HudDrgrAudit() {
  const [audits, setAudits] = useState([])
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    getHudDrgrAudits().then(data => { if (active) setAudits(data.audits) })
      .catch(err => { if (active) setError(err.message) })
      .finally(() => { if (active) setBusy(false) })
    return () => { active = false }
  }, [])
  async function refresh(create = false) {
    setBusy(true)
    setError('')
    try {
      if (create) await createHudDrgrAudit()
      setAudits((await getHudDrgrAudits()).audits)
    } catch (err) { setError(err.message) }
    finally { setBusy(false) }
  }
  return <section aria-label="HUD DRGR source audit" className="min-w-0 rounded-lg border border-border bg-card/50 p-4 lg:col-span-2">
    <h2 className="text-sm font-semibold">HUD DRGR source audit</h2>
    <p className="my-2 text-xs text-muted-foreground">Saved local snapshots. Source names and table hints identify candidates; authorization is unproven. No data is promoted.</p>
    <div className="flex flex-wrap gap-2">
      <Button className="min-h-11" variant="outline" disabled={busy} onClick={() => refresh()}>Refresh saved audits</Button>
      <Button className="min-h-11" variant="outline" disabled={busy} onClick={() => refresh(true)}>Create new audit snapshot</Button>
    </div>
    <p className="my-2 text-xs text-muted-foreground">Creating a snapshot re-inspects the configured local Financials paths and preserves earlier receipts. It does not download sources.</p>
    {busy && <p role="status">Loading audit results…</p>}
    {error && <p role="alert">{error} — saved results below may be stale. Refresh to retry.</p>}
    {!busy && !error && audits.length === 0 && <p>No saved audit receipts are available.</p>}
    {audits.map(audit => <details key={audit.path} className="my-3 rounded border border-border p-3 text-xs [overflow-wrap:anywhere]">
      <summary className="cursor-pointer">{audit.receipt?.generated_at_utc || audit.path} · {audit.state}</summary>
      <p className="my-2">Receipt SHA256: {audit.sha256}</p>
      <p>Receipt path: {audit.path}</p>
      {audit.error ? <p role="alert">{audit.error}</p> : <>
        <p className="my-2">Authorization: UNPROVEN · Raw result: {audit.receipt.result_state}</p>
        <p>{audit.receipt.blocker}</p>
        <p className="my-2">Classified: {audit.receipt.arithmetic.classified} / {audit.receipt.arithmetic.total} · Discovery candidates: {audit.receipt.arithmetic.authorized_candidates}</p>
        {audit.receipt.records.map((row, index) => <div key={index} className="my-2 border-t border-border pt-2">
          <p>{row.path}</p><p>{row.classification} · {row.inclusion_decision}</p>
          <p>Source SHA256: {row.sha256 || 'Unavailable'} · Rows: {row.logical_rows ?? 'Unknown'}</p>
        </div>)}
        <details><summary className="cursor-pointer">Full receipt metadata</summary><pre className="max-h-64 overflow-auto">{JSON.stringify(audit.receipt, null, 2)}</pre></details>
      </>}
    </details>)}
  </section>
}
