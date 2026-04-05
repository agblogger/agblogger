import { Loader2 } from 'lucide-react'
import type { ReferrerEntry } from '@/api/client'

interface TopReferrersPanelProps {
  referrers: ReferrerEntry[]
  isLoading: boolean
  error?: Error
}

export default function TopReferrersPanel({ referrers, isLoading, error }: TopReferrersPanelProps) {
  return (
    <div className="bg-surface border border-border rounded-lg p-5">
      <h3 className="text-sm font-medium text-ink mb-4">Top referrers</h3>
      {isLoading ? (
        <div
          className="flex items-center justify-center py-6"
          role="status"
          aria-label="Loading referrers"
        >
          <Loader2 size={16} className="text-accent animate-spin" aria-hidden="true" />
        </div>
      ) : error !== undefined ? (
        <p className="text-muted text-sm">Failed to load referrers. Please try again.</p>
      ) : referrers.length === 0 ? (
        <p className="text-muted text-sm">No referrer data for selected range.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left py-2 pr-4 text-muted font-medium">Referrer</th>
                <th className="text-right py-2 text-muted font-medium">Count</th>
              </tr>
            </thead>
            <tbody>
              {referrers.map((r) => (
                <tr key={r.referrer} className="border-b border-border last:border-0">
                  <td className="py-2 pr-4 text-ink">{r.referrer}</td>
                  <td className="py-2 text-right text-ink">{r.count.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
