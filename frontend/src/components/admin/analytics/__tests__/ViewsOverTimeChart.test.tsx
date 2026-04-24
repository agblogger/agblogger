import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { parseISO } from 'date-fns'
import ViewsOverTimeChart from '../ViewsOverTimeChart'
import type { DailyViewCount } from '@/api/client'

globalThis.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

function makeDays(count: number): DailyViewCount[] {
  const base = new Date(2024, 0, 1) // Jan 1, local time
  return Array.from({ length: count }, (_, i) => {
    const d = new Date(base)
    d.setDate(base.getDate() + i)
    const month = String(d.getMonth() + 1).padStart(2, '0')
    const day = String(d.getDate()).padStart(2, '0')
    return { date: `2024-${month}-${day}`, views: i + 1 }
  })
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

  it('renders "Views over time" heading for ≤30 days', () => {
    render(<ViewsOverTimeChart days={makeDays(7)} />)
    expect(screen.getByText('Views over time')).toBeInTheDocument()
    expect(screen.queryByText('Views per week')).not.toBeInTheDocument()
  })

  it('renders chart without empty state for ≤30 days', () => {
    render(<ViewsOverTimeChart days={makeDays(30)} />)
    expect(screen.queryByText('No data for selected range.')).not.toBeInTheDocument()
    expect(screen.getByText('Views over time')).toBeInTheDocument()
  })

  it('renders "Views per week" heading for >30 days', () => {
    render(<ViewsOverTimeChart days={makeDays(90)} />)
    expect(screen.getByText('Views per week')).toBeInTheDocument()
    expect(screen.queryByText('Views over time')).not.toBeInTheDocument()
  })

  it('renders chart without empty state for >30 days', () => {
    render(<ViewsOverTimeChart days={makeDays(90)} />)
    expect(screen.queryByText('No data for selected range.')).not.toBeInTheDocument()
  })

  it('weekly labels contain an en dash range separator', () => {
    render(<ViewsOverTimeChart days={makeDays(90)} />)
    // Recharts renders XAxis ticks as SVG <text> nodes; at least one should
    // contain the en dash (–) that separates the start and end of each week.
    const enDashLabels = screen.queryAllByText(/–/)
    expect(enDashLabels.length).toBeGreaterThan(0)
  })

  it('daily labels use locale-aware short date format', () => {
    render(<ViewsOverTimeChart days={makeDays(7)} />)
    // The first day is 2024-01-01. Its locale label must match what
    // Intl.DateTimeFormat produces — not the hardcoded "01-01" pattern.
    const expected = new Intl.DateTimeFormat(undefined, {
      month: 'numeric',
      day: 'numeric',
    }).format(parseISO('2024-01-01'))
    const labelNodes = screen.queryAllByText(expected)
    expect(labelNodes.length).toBeGreaterThan(0)
  })
})
