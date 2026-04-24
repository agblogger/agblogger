import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { parseISO } from 'date-fns'
import ViewsOverTimeChart from '../ViewsOverTimeChart'
import { bucketWeekly } from '../chartData'
import type { DailyViewCount } from '@/api/client'
import * as dateUtils from '@/utils/date'

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
    vi.spyOn(console, 'warn').mockImplementation(() => {}) // formatShortDate may warn in jsdom
    render(<ViewsOverTimeChart days={makeDays(7)} />)
    expect(screen.getByText('Views over time')).toBeInTheDocument()
    expect(screen.queryByText('Views per week')).not.toBeInTheDocument()
  })

  it('renders chart without empty state for ≤30 days', () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {}) // formatShortDate may warn in jsdom
    render(<ViewsOverTimeChart days={makeDays(30)} />)
    expect(screen.queryByText('No data for selected range.')).not.toBeInTheDocument()
    expect(screen.getByText('Views over time')).toBeInTheDocument()
  })

  it('renders "Views per week" heading for >30 days', () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {}) // bucketWeekly calls formatShortDate which may warn
    render(<ViewsOverTimeChart days={makeDays(90)} />)
    expect(screen.getByText('Views per week')).toBeInTheDocument()
    expect(screen.queryByText('Views over time')).not.toBeInTheDocument()
  })

  it('renders chart without empty state for >30 days', () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {}) // bucketWeekly calls formatShortDate which may warn
    render(<ViewsOverTimeChart days={makeDays(90)} />)
    expect(screen.queryByText('No data for selected range.')).not.toBeInTheDocument()
  })

  it('weekly labels contain an en dash range separator', () => {
    // bucketWeekly calls formatShortDate which may warn about date parsing in test env
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const days = makeDays(14) // two full weeks
    const buckets = bucketWeekly(days)
    expect(buckets).toHaveLength(2)
    expect(buckets[0]?.label).toContain('–')
    expect(buckets[1]?.label).toContain('–')
    warnSpy.mockRestore()
  })

  it('weekly bucket labels use locale-aware short date format', () => {
    // Mock formatLocalDate to work correctly with test dates
    const formatLocalDateMock = vi.fn((dateStr: string) => {
      // Extract YYYY-MM-DD and format it properly
      const match = dateStr.match(/^(\d{4})-(\d{2})-(\d{2})/)
      if (!match) return dateStr
      const date = parseISO(`${match[1]}-${match[2]}-${match[3]}T00:00:00Z`)
      return new Intl.DateTimeFormat(undefined, {
        month: 'numeric',
        day: 'numeric',
      }).format(date)
    })
    vi.spyOn(dateUtils, 'formatLocalDate').mockImplementation(formatLocalDateMock)

    const days = makeDays(14)
    const buckets = bucketWeekly(days)
    // Label must match what Intl.DateTimeFormat produces for the start date (2024-01-01)
    const expectedStart = new Intl.DateTimeFormat(undefined, {
      month: 'numeric',
      day: 'numeric',
    }).format(parseISO('2024-01-01T00:00:00Z'))
    expect(buckets[0]?.label).toMatch(new RegExp(`^${expectedStart.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`))
  })
})
