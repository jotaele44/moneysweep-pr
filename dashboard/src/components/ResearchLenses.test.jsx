import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ResearchLenses from './ResearchLenses'
import { getResearchLenses } from '@/lib/api'
import registry from '../../../registry/investigation_lenses_v1.json'

vi.mock('@/lib/api', () => ({ getResearchLenses: vi.fn() }))
afterEach(() => { cleanup(); vi.resetAllMocks() })
const response = {
  registry,
  summary: { declared_lenses: 24, required_lenses: 24, readiness: 'UNRESOLVED' },
  provenance: { source_revision: registry.source_revision, sha256: 'test-registry-hash' },
}
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(<QueryClientProvider client={client}><ResearchLenses /></QueryClientProvider>)
}
describe('research lens registry', () => {
  it('separates registry accounting from three readiness axes and exposes provenance', async () => {
    getResearchLenses.mockResolvedValue(response)
    mount()
    expect(await screen.findByText('24/24 lenses registered. Readiness: UNRESOLVED.')).toBeInTheDocument()
    expect(screen.getAllByRole('row')).toHaveLength(25)
    expect(screen.getAllByRole('cell', { name: 'UNATTEMPTED' })).toHaveLength(72)
    await userEvent.click(screen.getByText('Registry provenance'))
    expect(screen.getByText(registry.source_revision)).toBeVisible()
    await userEvent.click(screen.getByText('Inspect family lineages'))
    expect(screen.getByText(registry.lenses[0].falsification, { exact: false })).toBeVisible()
  })
  it('shows failure and permits recovery without an empty success', async () => {
    getResearchLenses.mockRejectedValueOnce(new Error('HTTP 503')).mockResolvedValue(response)
    mount()
    expect(await screen.findByRole('alert')).toHaveTextContent('HTTP 503')
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Refresh lenses' }))
    await waitFor(() => expect(screen.getByRole('table')).toBeVisible())
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
