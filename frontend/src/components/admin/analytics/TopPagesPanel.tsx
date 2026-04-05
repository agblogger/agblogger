import React, { useMemo, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { usePathReferrers } from '@/hooks/useAnalyticsDashboard'
import type { PathHit } from '@/api/client'

interface TopPagesPanelProps {
  paths: PathHit[]
}

interface ExpandedRow {
  path: string
  path_id: number
}

function ReferrerDetail({ pathId }: { pathId: number }) {
  const { data, error, isLoading } = usePathReferrers(pathId)

  if (isLoading) {
    return (
      <div
        className="flex items-center justify-center py-4"
        role="status"
        aria-label="Loading referrers"
      >
        <Loader2 size={14} className="text-accent animate-spin" aria-hidden="true" />
      </div>
    )
  }

  if (error !== undefined) {
    return (
      <p className="text-sm text-red-600 dark:text-red-400 py-2">
        Failed to load referrers. Please try again.
      </p>
    )
  }

  const referrers = data?.referrers ?? []

  if (referrers.length === 0) {
    return <p className="text-muted text-sm py-2">No referrers</p>
  }

  return (
    <table className="w-full text-sm mt-1">
      <thead>
        <tr className="border-b border-border">
          <th className="text-left py-1 pr-4 text-muted font-medium">Referrer</th>
          <th className="text-right py-1 text-muted font-medium">Count</th>
        </tr>
      </thead>
      <tbody>
        {referrers.map((r) => (
          <tr key={r.referrer} className="border-b border-border last:border-0">
            <td className="py-1 pr-4 text-ink">{r.referrer}</td>
            <td className="py-1 text-right text-ink">{r.count.toLocaleString()}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export default function TopPagesPanel({ paths }: TopPagesPanelProps) {
  const [expanded, setExpanded] = useState<ExpandedRow | null>(null)

  function handleRowClick(hit: PathHit) {
    setExpanded((prev) => (prev !== null && prev.path_id === hit.path_id ? null : { path: hit.path, path_id: hit.path_id }))
  }

  const sorted = useMemo(() => [...paths].sort((a, b) => b.views - a.views), [paths])

  return (
    <div className="bg-surface border border-border rounded-lg p-5">
      <h3 className="text-sm font-medium text-ink mb-4">Top pages</h3>
      {sorted.length === 0 ? (
        <p className="text-muted text-sm">No page data for selected range.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left py-2 pr-4 text-muted font-medium">Page path</th>
                <th className="text-right py-2 text-muted font-medium">Views</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((hit) => {
                const isExpanded = expanded !== null && expanded.path_id === hit.path_id
                return (
                  <React.Fragment key={hit.path}>
                    <tr
                      role="button"
                      tabIndex={0}
                      aria-expanded={isExpanded}
                      aria-label={`View referrers for ${hit.path}`}
                      className="border-b border-border last:border-0 hover:bg-base cursor-pointer transition-colors focus:outline-none focus:ring-2 focus:ring-accent/40"
                      onClick={() => { handleRowClick(hit) }}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault()
                          handleRowClick(hit)
                        }
                      }}
                    >
                      <td className="py-2 pr-4 text-ink font-mono text-xs">{hit.path}</td>
                      <td className="py-2 text-right text-ink">{hit.views.toLocaleString()}</td>
                    </tr>
                    {isExpanded && (
                      <tr className="border-b border-border last:border-0">
                        <td
                          colSpan={2}
                          className="pl-4 border-l-2 border-accent"
                        >
                          <ReferrerDetail pathId={hit.path_id} />
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
