import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import ViewsOverTimeChart from '../ViewsOverTimeChart'
import { bucketWeekly, formatShortDate } from '../chartData'
import type { DailyViewCount } from '@/api/client'
import { formatLocalDate } from '@/utils/date'

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

  it('renders "Views per week" heading for exactly 31 days (boundary)', () => {
    render(<ViewsOverTimeChart days={makeDays(31)} />)
    expect(screen.getByText('Views per week')).toBeInTheDocument()
    expect(screen.queryByText('Views over time')).not.toBeInTheDocument()
  })

  it('weekly labels contain an en dash range separator', () => {
    const days = makeDays(14) // two full weeks
    const buckets = bucketWeekly(days)
    expect(buckets).toHaveLength(2)
    expect(buckets[0]?.label).toContain('–')
    expect(buckets[1]?.label).toContain('–')
  })

  it('weekly bucket labels use locale-aware short date format', () => {
    const days = makeDays(14)
    const buckets = bucketWeekly(days)
    const expectedStart = formatLocalDate('2024-01-01', { month: 'numeric', day: 'numeric' })
    expect(buckets[0]?.label).toMatch(
      new RegExp(`^${expectedStart.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`)
    )
  })

  it('bucketWeekly sums views correctly within each bucket', () => {
    const days = makeDays(14) // views: 1..14
    const buckets = bucketWeekly(days)
    // First 7 days: 1+2+3+4+5+6+7 = 28
    expect(buckets[0]?.views).toBe(28)
    // Second 7 days: 8+9+10+11+12+13+14 = 77
    expect(buckets[1]?.views).toBe(77)
  })

  it('bucketWeekly handles a partial last week correctly', () => {
    const days = makeDays(9) // 7 + 2
    const buckets = bucketWeekly(days)
    expect(buckets).toHaveLength(2)
    // Second bucket: days 8 and 9 (views 8+9 = 17)
    expect(buckets[1]?.views).toBe(17)
    // End date of partial bucket is Jan 9
    const expectedEnd = formatLocalDate('2024-01-09', { month: 'numeric', day: 'numeric' })
    expect(buckets[1]?.label).toContain(expectedEnd)
  })

  it('bucketWeekly with a single-day input produces a single bucket with a range label', () => {
    const days: DailyViewCount[] = [{ date: '2024-01-01', views: 5 }]
    const buckets = bucketWeekly(days)
    expect(buckets).toHaveLength(1)
    expect(buckets[0]?.views).toBe(5)
    const expectedDate = formatLocalDate('2024-01-01', { month: 'numeric', day: 'numeric' })
    expect(buckets[0]?.label).toBe(`${expectedDate}–${expectedDate}`)
  })
})

describe('formatShortDate', () => {
  it('formats a YYYY-MM-DD date as locale-aware month/day', () => {
    const result = formatShortDate('2024-03-15')
    const expected = new Intl.DateTimeFormat(undefined, { month: 'numeric', day: 'numeric' }).format(
      new Date(2024, 2, 15),
    )
    expect(result).toBe(expected)
  })

  it('returns empty string for empty input', () => {
    expect(formatShortDate('')).toBe('')
  })

  it('returns [invalid date] for an invalid date string', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    expect(formatShortDate('not-a-date')).toBe('[invalid date]')
  })
})
