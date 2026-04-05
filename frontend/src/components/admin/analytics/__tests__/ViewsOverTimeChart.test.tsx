import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import ViewsOverTimeChart from '../ViewsOverTimeChart'
import type { DailyViewCount } from '@/api/client'

// Recharts uses ResizeObserver — provide a stub in jsdom
globalThis.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

function makeDays(count: number): DailyViewCount[] {
  return Array.from({ length: count }, (_, i) => ({
    date: `2024-01-${String(i + 1).padStart(2, '0')}`,
    views: i + 1,
  }))
}

describe('ViewsOverTimeChart', () => {
  it('renders "Views over time" heading', () => {
    render(<ViewsOverTimeChart days={[]} />)
    expect(screen.getByText('Views over time')).toBeInTheDocument()
  })

  it('shows empty state when days is empty', () => {
    render(<ViewsOverTimeChart days={[]} />)
    expect(screen.getByText('No data for selected range.')).toBeInTheDocument()
  })

  it('renders chart when days has data (≤30 days)', () => {
    const days = makeDays(7)
    render(<ViewsOverTimeChart days={days} />)
    expect(screen.queryByText('No data for selected range.')).not.toBeInTheDocument()
    // The chart container should be present
    expect(screen.getByText('Views over time')).toBeInTheDocument()
  })

  it('renders chart when days > 30 (weekly bucketing)', () => {
    const days = makeDays(90)
    render(<ViewsOverTimeChart days={days} />)
    expect(screen.queryByText('No data for selected range.')).not.toBeInTheDocument()
    expect(screen.getByText('Views over time')).toBeInTheDocument()
  })
})
