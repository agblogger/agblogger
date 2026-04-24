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
import { formatLocalDate } from '@/utils/date'
import { bucketWeekly, type ChartPoint } from './chartData'

interface ViewsOverTimeChartProps {
  days: DailyViewCount[]
}

function formatShortDate(date: string): string {
  return formatLocalDate(date, { month: 'numeric', day: 'numeric' })
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
