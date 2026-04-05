import { useState } from 'react'
import type { CSSProperties } from 'react'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'
import { useBreakdownDetail } from '@/hooks/useAnalyticsDashboard'
import type { BreakdownEntry } from '@/api/client'
import type { BreakdownDetailCategory } from '@/api/client'

const POINTER_CURSOR: CSSProperties = { cursor: 'pointer' }

interface BreakdownBarChartProps {
  title: string
  entries: BreakdownEntry[]
  drillDownCategory?: BreakdownDetailCategory
}

interface DrillDownDetail {
  name: string
  entryId: string
}

function VersionDetail({
  category,
  entryId,
  onClose,
}: {
  category: BreakdownDetailCategory
  entryId: string
  onClose: () => void
}) {
  const { data, error, isLoading } = useBreakdownDetail(category, entryId)

  return (
    <div className="mt-3 pl-4 border-l-2 border-accent">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs text-muted font-medium">Version breakdown</span>
        <button
          onClick={onClose}
          className="text-xs text-muted hover:text-ink transition-colors"
        >
          Close
        </button>
      </div>
      {isLoading ? (
        <p className="text-xs text-muted py-2">Loading...</p>
      ) : error !== undefined ? (
        <p className="text-xs text-red-600 dark:text-red-400">Failed to load details.</p>
      ) : data === undefined || data.entries.length === 0 ? (
        <p className="text-xs text-muted">No version data.</p>
      ) : (
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border">
              <th className="text-left py-1 pr-4 text-muted font-medium">Name</th>
              <th className="text-right py-1 text-muted font-medium">%</th>
            </tr>
          </thead>
          <tbody>
            {data.entries.map((e) => (
              <tr key={e.name} className="border-b border-border last:border-0">
                <td className="py-1 pr-4 text-ink">{e.name}</td>
                <td className="py-1 text-right text-ink">{e.percent.toFixed(1)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

export default function BreakdownBarChart({
  title,
  entries,
  drillDownCategory,
}: BreakdownBarChartProps) {
  const [drillDown, setDrillDown] = useState<DrillDownDetail | null>(null)

  const topEntries = entries.slice(0, 8)

  function handleBarClick(_data: unknown, index: number) {
    if (drillDownCategory === undefined) return
    const entry = topEntries[index]
    if (entry === undefined) return

    const entryId = entry.gc_id
    if (entryId === undefined || entryId === null || entryId === '') return
    setDrillDown((prev) => (prev !== null && prev.entryId === entryId ? null : { name: entry.name, entryId }))
  }

  return (
    <div className="bg-surface border border-border rounded-lg p-5">
      <h3 className="text-sm font-medium text-ink mb-4">{title}</h3>
      {topEntries.length === 0 ? (
        <p className="text-muted text-sm">No data.</p>
      ) : (
        <>
          <ResponsiveContainer width="100%" height={Math.max(100, topEntries.length * 24)}>
            <BarChart
              data={topEntries}
              layout="vertical"
              margin={{ left: 0, right: 8, top: 0, bottom: 0 }}
              onClick={(chartData) => {
                if (chartData.activeTooltipIndex != null && typeof chartData.activeTooltipIndex === 'number') {
                  handleBarClick(null, chartData.activeTooltipIndex)
                }
              }}
            >
              <XAxis type="number" tick={{ fontSize: 10 }} unit="%" />
              <YAxis
                type="category"
                dataKey="name"
                tick={{ fontSize: 10 }}
                width={70}
              />
              <Tooltip formatter={(v) => [`${v as number}%`, 'Share']} />
              <Bar
                dataKey="percent"
                fill="var(--color-accent, #6366f1)"
                fillOpacity={0.75}
                style={drillDownCategory !== undefined ? POINTER_CURSOR : undefined}
              />
            </BarChart>
          </ResponsiveContainer>

          {drillDown !== null && drillDownCategory !== undefined && (
            <VersionDetail
              category={drillDownCategory}
              entryId={drillDown.entryId}
              onClose={() => { setDrillDown(null) }}
            />
          )}
        </>
      )}
    </div>
  )
}
