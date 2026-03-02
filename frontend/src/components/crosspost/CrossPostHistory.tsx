import type { CrossPostResult } from '@/api/crosspost'
import PlatformIcon from '@/components/crosspost/PlatformIcon'
import { formatDate } from '@/utils/date'

interface CrossPostHistoryProps {
  items: CrossPostResult[]
  loading: boolean
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1)
}

export default function CrossPostHistory({ items, loading }: CrossPostHistoryProps) {
  if (loading) {
    return <p className="text-sm text-muted">Loading history...</p>
  }

  if (items.length === 0) {
    return <p className="text-sm text-muted">Not shared yet.</p>
  }

  return (
    <div className="space-y-2">
      {items.map((item) => (
        <div key={item.id} className="flex items-center gap-3 text-sm">
          <PlatformIcon platform={item.platform} size={16} className="text-muted" />
          <span className="font-medium text-ink">{capitalize(item.platform)}</span>
          {item.status === 'posted' ? (
            <span className="bg-green-100 text-green-700 rounded-full px-2 py-0.5 text-xs font-medium">
              Posted
            </span>
          ) : (
            <span className="bg-red-100 text-red-600 rounded-full px-2 py-0.5 text-xs font-medium">
              Failed
            </span>
          )}
          {item.posted_at !== null && (
            <span className="text-muted text-xs">
              {formatDate(item.posted_at, 'MMM d, yyyy h:mm a')}
            </span>
          )}
          {item.status === 'failed' && item.error !== null && (
            <span className="text-xs text-red-600">{item.error}</span>
          )}
        </div>
      ))}
    </div>
  )
}
