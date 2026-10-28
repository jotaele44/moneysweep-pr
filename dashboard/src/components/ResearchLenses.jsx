import { useQuery } from '@tanstack/react-query'
import { getResearchLenses } from '@/lib/api'

export default function ResearchLenses() {
  const { data, error, isPending, isFetching, refetch } = useQuery({
    queryKey: ['research-lenses'], queryFn: getResearchLenses, retry: false,
  })
  return (
    <section className="h-full overflow-auto p-4" aria-labelledby="research-lenses-title">
      <h2 id="research-lenses-title" className="text-lg font-semibold">Research lenses</h2>
      <p className="my-2">Development coverage for family, corporate, institutional and political research. Registry coverage does not certify working investigations or findings.</p>
      <button type="button" className="rounded border p-2" disabled={isFetching} onClick={() => refetch()}>
        {isFetching ? 'Loading lenses…' : 'Refresh lenses'}
      </button>
      {isPending && <p role="status">Loading research lens registry…</p>}
      {error && <p role="alert">Research lens registry unavailable. {error.message}</p>}
      {!error && data && <>
        <p className="my-3" role="status">{data.summary.declared_lenses}/{data.summary.required_lenses} lenses registered. Readiness: {data.summary.readiness}.</p>
        <details className="my-3"><summary>Registry provenance</summary>
          <p>Baseline revision: <code>{data.provenance.source_revision}</code></p>
          <p>Registry SHA-256: <code className="break-all">{data.provenance.sha256}</code></p>
        </details>
        <table className="w-full text-left text-sm">
          <caption className="text-left">Implementation, source coverage and findings are assessed separately.</caption>
          <thead><tr>{['Lens', 'Implementation', 'Sources', 'Findings', 'Research contract'].map(label => <th key={label} scope="col" className="border-b p-2">{label}</th>)}</tr></thead>
          <tbody>{data.registry.lenses.map(lens => <tr key={lens.id}>
            <th scope="row" className="border-b p-2 align-top">{lens.id.replaceAll('_', ' ')}</th>
            <td className="border-b p-2 align-top">{lens.implementation_state}</td>
            <td className="border-b p-2 align-top">{lens.source_coverage_state}</td>
            <td className="border-b p-2 align-top">{lens.finding_state}</td>
            <td className="border-b p-2"><details><summary>Inspect {lens.id.replaceAll('_', ' ')}</summary>
              <p>{lens.question}</p><p>Sources: {lens.source_families.join(', ')}</p>
              <p>Relationships: {lens.predicates.join(', ')}</p><p>Falsification: {lens.falsification}</p>
              <ul>{Object.entries(lens.gates).map(([gate, value]) => <li key={gate}>{gate}: {value.state}</li>)}</ul>
            </details></td>
          </tr>)}</tbody>
        </table>
      </>}
    </section>
  )
}
