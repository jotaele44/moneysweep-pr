import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CampaignFinance from './CampaignFinance'
import {
  useCampaignFinanceContributions,
  useCampaignFinanceEntities,
  useCampaignFinanceReports,
  useCampaignFinanceSummary,
} from '@/lib/hooks'

vi.mock('@/lib/hooks', () => ({
  useCampaignFinanceContributions: vi.fn(),
  useCampaignFinanceEntities: vi.fn(),
  useCampaignFinanceReports: vi.fn(),
  useCampaignFinanceSummary: vi.fn(),
}))

const query = (data) => ({
  data,
  dataUpdatedAt: Date.now(),
  error: null,
  fetchStatus: 'idle',
  isError: false,
  isFetching: false,
  isLoading: false,
  isPending: false,
  isStale: false,
  refetch: vi.fn(),
})

describe('CampaignFinance', () => {
  beforeEach(() => {
    useCampaignFinanceContributions.mockReturnValue(query({ rows: [], total: 0 }))
    useCampaignFinanceEntities.mockReturnValue(query([]))
    useCampaignFinanceReports.mockReturnValue(query([]))
  })

  it('shows an explicit repository-backed empty state', () => {
    useCampaignFinanceSummary.mockReturnValue(query({
      sources: [],
      derived: {},
      hasData: false,
      totalContributionRows: 0,
      totalContributionAmount: null,
      totalFederalOutflowRows: 0,
      emptyState: 'No campaign-finance datasets are materialized in this repository checkout.',
    }))

    render(<CampaignFinance />)

    expect(screen.getByText(
      'No campaign-finance datasets are materialized in this repository checkout.',
    )).toBeInTheDocument()
    expect(screen.getByText('No campaign-finance contributions are materialized')).toBeInTheDocument()
  })

  it('shows an em dash, not $0, for the signed amount when no source reports one', () => {
    useCampaignFinanceSummary.mockReturnValue(query({
      sources: [],
      derived: {},
      hasData: false,
      totalContributionRows: 0,
      totalContributionAmount: null,
      totalFederalOutflowRows: 0,
      emptyState: 'No campaign-finance datasets are materialized in this repository checkout.',
    }))

    render(<CampaignFinance />)

    const tile = screen.getByText('Signed amount').parentElement
    expect(tile).toHaveTextContent('—')
    expect(tile).not.toHaveTextContent('$0')
  })

  it('still shows a genuine zero total as $0', () => {
    useCampaignFinanceSummary.mockReturnValue(query({
      sources: [{ source: 'oce', rows: 1, amount: 0, status: 'available' }],
      derived: {},
      hasData: true,
      totalContributionRows: 1,
      totalContributionAmount: 0,
      totalFederalOutflowRows: 0,
    }))

    render(<CampaignFinance />)

    expect(screen.getByText('Signed amount').parentElement).toHaveTextContent('$0')
  })

  it('shows an error banner instead of the empty-state banner when the summary request fails', () => {
    useCampaignFinanceSummary.mockReturnValue({
      ...query(undefined),
      error: new Error('summary → HTTP 500'),
      isError: true,
    })

    render(<CampaignFinance />)

    expect(screen.getByText('Campaign-finance summary failed to load')).toBeInTheDocument()
    expect(screen.queryByText('No campaign-finance datasets are materialized.')).not.toBeInTheDocument()
  })
})
