import { useMemo } from 'react'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'
import type { DailyViewCount } from '@/api/client'

interface ViewsOverTimeChartProps {
  days: DailyViewCount[]
}

interface ChartPoint {
  label: string
  views: number
}

function formatShortDate(date: string): string {
  // date is YYYY-MM-DD; parse it as UTC and format with locale-aware short date format
  const parts = date.split('-')
  if (
    parts.length !== 3 ||
    parts[0] == null ||
    parts[1] == null ||
    parts[2] == null
  ) {
    return date
  }
  // Create a date from these components (interpreted as UTC)
  const d = new Date(`${parts[0]}-${parts[1]}-${parts[2]}T00:00:00Z`)
  return new Intl.DateTimeFormat(undefined, {
    month: 'numeric',
    day: 'numeric',
  }).format(d)
}

function bucketWeekly(days: DailyViewCount[]): ChartPoint[] {
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

export default function ViewsOverTimeChart({ days }: ViewsOverTimeChartProps) {
  const isWeekly = days.length > 30
  const chartData = useMemo<ChartPoint[]>(() => {
    if (days.length === 0) return []
    if (days.length <= 30) {
      return days.map((d) => ({ label: formatShortDate(d.date), views: d.views }))
    }
    return bucketWeekly(days)
  }, [days])

  return (
    <div className="bg-surface border border-border rounded-lg p-5">
      <h3 className="text-sm font-medium text-ink mb-4">
        {isWeekly ? 'Views per week' : 'Views over time'}
      </h3>
      {days.length === 0 ? (
        <p className="text-muted text-sm">No data for selected range.</p>
      ) : (
        <ResponsiveContainer width="100%" height={180}>
          <BarChart
            data={chartData}
            margin={{ left: 0, right: 8, top: 0, bottom: 0 }}
          >
            <XAxis
              dataKey="label"
              tick={{ fontSize: 10 }}
              interval="preserveStartEnd"
            />
            <YAxis tick={{ fontSize: 10 }} />
            <Tooltip />
            <Bar
              dataKey="views"
              fill="var(--color-accent, #6366f1)"
              fillOpacity={0.75}
            />
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}
