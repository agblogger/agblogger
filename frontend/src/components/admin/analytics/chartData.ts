import type { DailyViewCount } from '@/api/client'
import { formatLocalDate } from '@/utils/date'

export interface ChartPoint {
  label: string
  views: number
}

export function formatShortDate(date: string): string {
  return formatLocalDate(date, { month: 'numeric', day: 'numeric' })
}

export function bucketWeekly(days: DailyViewCount[]): ChartPoint[] {
  const buckets: ChartPoint[] = []
  for (let i = 0; i < days.length; i += 7) {
    const chunk = days.slice(i, i + 7)
    const total = chunk.reduce((sum, d) => sum + d.views, 0)
    const start = chunk[0]?.date ?? ''
    const end = chunk[chunk.length - 1]?.date ?? start
    buckets.push({ label: `${formatShortDate(start)}–${formatShortDate(end)}`, views: total })
  }
  return buckets
}
