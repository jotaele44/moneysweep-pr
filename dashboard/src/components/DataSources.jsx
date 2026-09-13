import { useEffect, useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  deleteCredential,
  getCredentialStatus,
  getMaterializationSources,
  getMaterializationStatus,
  materializeOfflineSource,
  runApiMaterialization,
  saveCredential,
  stageOfflineFile,
} from '@/lib/api'

function JsonResult({ value }) {
  if (!value) return null
  return (
    <pre className="max-h-48 overflow-auto rounded-md border border-border bg-card/60 p-3 text-[11px] leading-relaxed text-muted-foreground">
      {JSON.stringify(value, null, 2)}
    </pre>
  )
}

function NativeSelect({ value, onChange, children, label }) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      aria-label={label}
      className="min-h-11 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground"
    >
      {children}
    </select>
  )
}

export default function DataSources() {
  const [status, setStatus] = useState(null)
  const [sources, setSources] = useState([])
  const [credentials, setCredentials] = useState({ keys: {}, allowedKeys: [] })
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)

  const [manualSource, setManualSource] = useState('')
  const [offlineFile, setOfflineFile] = useState(null)
  const [apiSource, setApiSource] = useState('')
  const [credentialKey, setCredentialKey] = useState('')
  const [credentialValue, setCredentialValue] = useState('')

  const manualSources = useMemo(
    () => sources.filter((s) => Boolean(s.manualDropDir)),
    [sources],
  )
  const apiSources = useMemo(
    () => sources.filter((s) => s.automatable),
    [sources],
  )

  const refresh = async () => {
    const [nextStatus, nextSources, nextCredentials] = await Promise.all([
      getMaterializationStatus(),
      getMaterializationSources(),
      getCredentialStatus(),
    ])
    setStatus(nextStatus)
    setSources(nextSources)
    setCredentials(nextCredentials)
    setManualSource((current) => current || nextSources.find((s) => s.manualDropDir)?.sourceId || '')
    setApiSource((current) => {
      if (current) return current
      const preferred = nextSources.find((s) => s.sourceId === 'fema_pa_openfema_v2' && s.automatable)
      return preferred?.sourceId || nextSources.find((s) => s.automatable)?.sourceId || ''
    })
    setCredentialKey((current) => current || nextCredentials.allowedKeys?.[0] || '')
  }

  useEffect(() => {
    let active = true
    ;(async () => {
      try {
        await refresh()
      } catch (err) {
        if (active) setError(err.message)
      } finally {
        if (active) setLoading(false)
      }
    })()
    return () => { active = false }
  }, [])

  const execute = async (name, fn) => {
    setBusy(name)
    setError('')
    setResult(null)
    try {
      const next = await fn()
      setResult(next)
      await refresh()
      return next
    } catch (err) {
      setError(err.message)
      return null
    } finally {
      setBusy('')
    }
  }

  const onRefresh = async () => {
    setBusy('refresh')
    setError('')
    try {
      await refresh()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy('')
    }
  }

  const onStage = () => execute('stage', async () => {
    if (!manualSource) throw new Error('Select a registered manual source')
    if (!offlineFile) throw new Error('Choose an offline file first')
    return stageOfflineFile(manualSource, offlineFile)
  })

  const onMaterializeOffline = () => execute('offline-run', async () => {
    if (!manualSource) throw new Error('Select a registered manual source')
    return materializeOfflineSource(manualSource)
  })

  const onApi = (dryRun) => execute(dryRun ? 'api-dry' : 'api-live', async () => {
    if (!apiSource) throw new Error('Select an automatable source')
    return runApiMaterialization({ source: apiSource, dryRun })
  })

  const onSaveCredential = () => execute('credential-save', async () => {
    if (!credentialKey) throw new Error('Select a credential key')
    if (!credentialValue.trim()) throw new Error('Enter a credential value')
    const response = await saveCredential(credentialKey, credentialValue)
    setCredentialValue('')
    return response
  })

  const onDeleteCredential = () => execute('credential-delete', async () => {
    if (!credentialKey) throw new Error('Select a credential key')
    return deleteCredential(credentialKey)
  })

  if (loading) {
    return <div className="p-6 text-sm text-muted-foreground">Loading data-plane status…</div>
  }

  const readiness = status?.readiness ?? {}
  const production = status?.production ?? {}
  const automatableTotal = readiness.automatable_total ?? apiSources.length

  return (
    <div className="ms-scroll-region h-full overflow-auto p-4">
      <div className="mx-auto grid max-w-6xl gap-4 lg:grid-cols-2">
        <section className="rounded-lg border border-border bg-card/50 p-4 lg:col-span-2">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-foreground">Data-plane state</h2>
              <p className="mt-1 text-xs text-muted-foreground">
                Immutable source registry + writable local workspace. Materialization never promotes by filename alone.
              </p>
            </div>
            <Button variant="outline" className="min-h-11" onClick={onRefresh} disabled={Boolean(busy)}>
              Refresh
            </Button>
          </div>
          <dl className="mt-4 grid gap-3 text-xs sm:grid-cols-2 lg:grid-cols-5">
            <div><dt className="text-muted-foreground">Registered</dt><dd className="mt-1 font-mono text-foreground">{status?.registeredSources ?? '—'}</dd></div>
            <div><dt className="text-muted-foreground">Automatable</dt><dd className="mt-1 font-mono text-foreground">{automatableTotal}</dd></div>
            <div><dt className="text-muted-foreground">Manual exports</dt><dd className="mt-1 font-mono text-foreground">{readiness.queued_excluded?.manual_export ?? status?.manualExportSources ?? '—'}</dd></div>
            <div><dt className="text-muted-foreground">Source-ID hash</dt><dd className="mt-1 truncate font-mono text-foreground" title={readiness.source_count_provenance?.source_ids_sha256}>{readiness.source_count_provenance?.source_ids_sha256?.slice(0, 12) ?? '—'}…</dd></div>
            <div><dt className="text-muted-foreground">Production</dt><dd className="mt-1 font-mono text-foreground">{production.production_status ?? 'UNKNOWN'}</dd></div>
          </dl>
        </section>

        <section className="rounded-lg border border-border bg-card/50 p-4">
          <h2 className="text-sm font-semibold text-foreground">Offline files</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Stage an operator-supplied export into its registered dropzone. Exact bytes are SHA-256 hashed and preserved before any producer runs.
          </p>
          <div className="mt-4 space-y-3">
            <NativeSelect value={manualSource} onChange={setManualSource} label="Manual source">
              {manualSources.map((source) => (
                <option key={source.sourceId} value={source.sourceId}>{source.sourceId}</option>
              ))}
            </NativeSelect>
            <div className="text-[11px] text-muted-foreground">
              Dropzone: {manualSources.find((s) => s.sourceId === manualSource)?.manualDropDir || '—'}
              {' · '}Pattern: {manualSources.find((s) => s.sourceId === manualSource)?.manualFilenamePattern || '—'}
            </div>
            <Input
              type="file"
              aria-label="Choose offline source file"
              className="min-h-11 bg-background text-xs"
              onChange={(e) => setOfflineFile(e.target.files?.[0] ?? null)}
            />
            <div className="flex flex-wrap gap-2">
              <Button className="min-h-11" onClick={onStage} disabled={Boolean(busy) || !offlineFile}>Stage + hash</Button>
              <Button variant="outline" className="min-h-11" onClick={onMaterializeOffline} disabled={Boolean(busy) || !manualSource}>
                Materialize staged source
              </Button>
            </div>
            <p className="text-[11px] text-muted-foreground">Staging state is <code>STAGED_NOT_PROMOTED</code>. Producer success is not canonical promotion.</p>
          </div>
        </section>

        <section className="rounded-lg border border-border bg-card/50 p-4">
          <h2 className="text-sm font-semibold text-foreground">API materialization</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Start one classifier-approved automatable source at a time. Dry-run performs source selection only; live run performs egress gating and preserves a versioned run receipt.
          </p>
          <div className="mt-4 space-y-3">
            <NativeSelect value={apiSource} onChange={setApiSource} label="API materialization source">
              {apiSources.map((source) => (
                <option key={source.sourceId} value={source.sourceId}>
                  {source.sourceId}{source.required ? ' · required' : ''}{source.requiredSecret ? ` · ${source.requiredSecret}` : ''}
                </option>
              ))}
            </NativeSelect>
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" className="min-h-11" onClick={() => onApi(true)} disabled={Boolean(busy) || !apiSource}>Dry run</Button>
              <Button className="min-h-11" onClick={() => onApi(false)} disabled={Boolean(busy) || !apiSource}>Fetch + materialize</Button>
            </div>
            <p className="text-[11px] text-muted-foreground">The GUI intentionally omits a one-click “run all {automatableTotal}” action to prevent accidental large network/API runs.</p>
          </div>
        </section>

        <section className="rounded-lg border border-border bg-card/50 p-4 lg:col-span-2">
          <h2 className="text-sm font-semibold text-foreground">API credentials</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Stored in the operating-system credential vault. MoneySweep reports configured/not configured only; secret values are never read back into the GUI.
          </p>
          <div className="mt-4 grid gap-3 md:grid-cols-[minmax(220px,1fr)_minmax(260px,2fr)_auto_auto]">
            <NativeSelect value={credentialKey} onChange={setCredentialKey} label="Credential key">
              {(credentials.allowedKeys ?? []).map((key) => (
                <option key={key} value={key}>{key} · {credentials.keys?.[key] ? 'configured' : 'not configured'}</option>
              ))}
            </NativeSelect>
            <Input
              type="password"
              autoComplete="off"
              value={credentialValue}
              onChange={(e) => setCredentialValue(e.target.value)}
              placeholder="Paste key; value will not be echoed"
              aria-label="API credential value"
              className="min-h-11 bg-background text-sm"
            />
            <Button className="min-h-11" onClick={onSaveCredential} disabled={Boolean(busy) || !credentialValue.trim()}>Save to vault</Button>
            <Button variant="outline" className="min-h-11" onClick={onDeleteCredential} disabled={Boolean(busy) || !credentialKey}>Remove</Button>
          </div>
        </section>

        {(busy || error || result) && (
          <section className="rounded-lg border border-border bg-card/50 p-4 lg:col-span-2" aria-live="polite">
            <h2 className="text-sm font-semibold text-foreground">Operation result</h2>
            {busy && <p className="mt-2 text-xs text-muted-foreground">Running {busy}…</p>}
            {error && <p className="mt-2 text-xs text-destructive">{error}</p>}
            <div className="mt-3"><JsonResult value={result} /></div>
          </section>
        )}
      </div>
    </div>
  )
}
