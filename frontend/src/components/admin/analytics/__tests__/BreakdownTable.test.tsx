import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import BreakdownTable from '../BreakdownTable'
import type { BreakdownEntry } from '@/api/client'

const DEFAULT_ENTRIES: BreakdownEntry[] = [
  { name: 'United States', count: 1200, percent: 60.0 },
  { name: 'Germany', count: 400, percent: 20.0 },
  { name: 'France', count: 200, percent: 10.0 },
]

describe('BreakdownTable', () => {
  it('renders the title', () => {
    render(<BreakdownTable title="Locations" nameLabel="Country" entries={[]} />)
    expect(screen.getByText('Locations')).toBeInTheDocument()
  })

  it('uses custom nameLabel as column header', () => {
    render(<BreakdownTable title="Languages" nameLabel="Language" entries={DEFAULT_ENTRIES} />)
    expect(screen.getByText('Language')).toBeInTheDocument()
  })

  it('uses custom nameLabel for campaigns', () => {
    render(<BreakdownTable title="Campaigns" nameLabel="Campaign" entries={DEFAULT_ENTRIES} />)
    expect(screen.getByText('Campaign')).toBeInTheDocument()
  })

  it('renders entry names, counts, and percentages', () => {
    render(<BreakdownTable title="Locations" nameLabel="Country" entries={DEFAULT_ENTRIES} />)
    expect(screen.getByText('United States')).toBeInTheDocument()
    expect(screen.getByText('1,200')).toBeInTheDocument()
    expect(screen.getByText('60.0%')).toBeInTheDocument()
    expect(screen.getByText('Germany')).toBeInTheDocument()
    expect(screen.getByText('400')).toBeInTheDocument()
    expect(screen.getByText('20.0%')).toBeInTheDocument()
  })

  it('shows "No data." when entries is empty', () => {
    render(<BreakdownTable title="Sizes" nameLabel="Screen Size" entries={[]} />)
    expect(screen.getByText('No data.')).toBeInTheDocument()
  })

  it('renders Visitors and % column headers', () => {
    render(<BreakdownTable title="Locations" nameLabel="Country" entries={DEFAULT_ENTRIES} />)
    expect(screen.getByText('Visitors')).toBeInTheDocument()
    expect(screen.getByText('%')).toBeInTheDocument()
  })
})
