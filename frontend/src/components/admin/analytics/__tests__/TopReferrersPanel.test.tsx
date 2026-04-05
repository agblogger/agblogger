import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import TopReferrersPanel from '../TopReferrersPanel'
import type { ReferrerEntry } from '@/api/client'

const DEFAULT_REFERRERS: ReferrerEntry[] = [
  { referrer: 'https://news.ycombinator.com', count: 123 },
  { referrer: 'https://reddit.com', count: 45 },
]

describe('TopReferrersPanel', () => {
  it('renders "Top referrers" heading', () => {
    render(<TopReferrersPanel referrers={[]} isLoading={false} />)
    expect(screen.getByText('Top referrers')).toBeInTheDocument()
  })

  it('renders referrer entries', () => {
    render(<TopReferrersPanel referrers={DEFAULT_REFERRERS} isLoading={false} />)
    expect(screen.getByText('https://news.ycombinator.com')).toBeInTheDocument()
    expect(screen.getByText('123')).toBeInTheDocument()
    expect(screen.getByText('https://reddit.com')).toBeInTheDocument()
    expect(screen.getByText('45')).toBeInTheDocument()
  })

  it('shows empty state when referrers is empty', () => {
    render(<TopReferrersPanel referrers={[]} isLoading={false} />)
    expect(screen.getByText('No referrer data for selected range.')).toBeInTheDocument()
  })

  it('shows loading spinner when isLoading=true', () => {
    render(<TopReferrersPanel referrers={[]} isLoading={true} />)
    expect(screen.getByRole('status', { name: /Loading referrers/i })).toBeInTheDocument()
    expect(screen.queryByText('No referrer data for selected range.')).not.toBeInTheDocument()
  })

  it('renders Referrer and Count column headers', () => {
    render(<TopReferrersPanel referrers={DEFAULT_REFERRERS} isLoading={false} />)
    expect(screen.getByText('Referrer')).toBeInTheDocument()
    expect(screen.getByText('Count')).toBeInTheDocument()
  })

  it('shows error state when error prop is provided', () => {
    render(<TopReferrersPanel referrers={[]} isLoading={false} error={new Error('Network error')} />)
    expect(screen.getByText('Failed to load referrers. Please try again.')).toBeInTheDocument()
    expect(screen.queryByText('No referrer data for selected range.')).not.toBeInTheDocument()
  })
})
