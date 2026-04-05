import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { SWRConfig } from 'swr'
import type { BreakdownEntry } from '@/api/client'

const mockFetchBreakdownDetail = vi.fn()

vi.mock('@/api/analytics', () => ({
  fetchBreakdownDetail: (...args: unknown[]) => mockFetchBreakdownDetail(...args) as unknown,
}))

// Recharts uses ResizeObserver — provide a stub in jsdom
globalThis.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

import BreakdownBarChart from '../BreakdownBarChart'

const DEFAULT_ENTRIES: BreakdownEntry[] = [
  { name: 'Chrome', count: 500, percent: 72.3 },
  { name: 'Firefox', count: 192, percent: 27.7 },
]

function renderChart(
  entries: BreakdownEntry[] = DEFAULT_ENTRIES,
  title = 'Browsers',
  drillDownCategory?: 'browsers' | 'systems',
) {
  const extraProps = drillDownCategory !== undefined ? { drillDownCategory } : {}
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0, shouldRetryOnError: false }}>
      <BreakdownBarChart
        title={title}
        entries={entries}
        {...extraProps}
      />
    </SWRConfig>,
  )
}

describe('BreakdownBarChart', () => {
  it('renders the title', () => {
    renderChart()
    expect(screen.getByText('Browsers')).toBeInTheDocument()
  })

  it('renders with custom title', () => {
    renderChart(DEFAULT_ENTRIES, 'Operating Systems')
    expect(screen.getByText('Operating Systems')).toBeInTheDocument()
  })

  it('shows empty state when entries is empty', () => {
    renderChart([])
    expect(screen.getByText('No data.')).toBeInTheDocument()
  })

  it('does not show empty state when entries are present', () => {
    renderChart()
    expect(screen.queryByText('No data.')).not.toBeInTheDocument()
  })

  it('renders chart without drill-down category', () => {
    renderChart(DEFAULT_ENTRIES, 'Browsers', undefined)
    // No version detail
    expect(screen.queryByText('Version breakdown')).not.toBeInTheDocument()
  })
})
