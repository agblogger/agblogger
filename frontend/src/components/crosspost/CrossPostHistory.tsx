import type { CrossPostResult } from '@/api/crosspost'
import PlatformIcon from '@/components/crosspost/PlatformIcon'
import { formatLocalDate } from '@/utils/date'

interface CrossPostHistoryProps {
  items: CrossPostResult[]
  loading: boolean
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1)
}

export default function CrossPostHistory({ items, loading }: CrossPostHistoryProps) {
  if (loading) {
    return <p className="text-sm text-muted">Loading cross-post history...</p>
  }

  if (items.length === 0) {
    return <p className="text-sm text-muted">No cross-posts yet.</p>
  }

  return (
    <div className="space-y-2">
      {items.map((item) => (
        <div key={item.id} className="flex items-center gap-3 text-sm">
          <PlatformIcon platform={item.platform} size={16} className="text-muted" />
          <span className="font-medium text-ink">{capitalize(item.platform)}</span>
          {item.status === 'posted' ? (
            <span className="bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 rounded-full px-2 py-0.5 text-xs font-medium">
              Posted
            </span>
          ) : (
            <span className="bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400 rounded-full px-2 py-0.5 text-xs font-medium">
              Failed
            </span>
          )}
          {item.posted_at !== null && (
            <span className="text-muted text-xs">
              {formatLocalDate(item.posted_at, { dateStyle: 'medium', timeStyle: 'short' })}
            </span>
          )}
          {item.status === 'failed' && item.error !== null && (
            <span className="text-xs text-red-600 dark:text-red-400">{item.error}</span>
          )}
        </div>
      ))}
    </div>
  )
}
