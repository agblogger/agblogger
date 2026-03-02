import { useEffect, useState } from 'react'
import LoadingSpinner from '@/components/LoadingSpinner'
import { Link } from 'react-router-dom'
import { Tag, Settings } from 'lucide-react'

import { useAuthStore } from '@/stores/authStore'
import { fetchLabels } from '@/api/labels'
import { HTTPError } from '@/api/client'
import type { LabelResponse } from '@/api/client'
import LabelGraphPage from '@/pages/LabelGraphPage'

export default function LabelsPage() {
  const [view, setView] = useState<'list' | 'graph'>('list')

  const viewToggle = (
    <div className="flex items-center bg-paper-warm rounded-lg p-0.5 border border-border">
      <button
        onClick={() => setView('list')}
        aria-pressed={view === 'list'}
        className={`px-3 py-1.5 text-sm font-medium rounded-md transition-all ${
          view === 'list'
            ? 'bg-accent text-white shadow-sm'
            : 'text-muted hover:text-ink'
        }`}
      >
        List
      </button>
      <button
        onClick={() => setView('graph')}
        aria-pressed={view === 'graph'}
        className={`px-3 py-1.5 text-sm font-medium rounded-md transition-all ${
          view === 'graph'
            ? 'bg-accent text-white shadow-sm'
            : 'text-muted hover:text-ink'
        }`}
      >
        Graph
      </button>
    </div>
  )

  return (
    <div className="animate-fade-in">
      {view === 'list' ? (
        <>
          <div className="flex items-center justify-between mb-8">
            <div className="flex items-center gap-3">
              <Tag size={20} className="text-accent" />
              <h1 className="font-display text-3xl text-ink">Labels</h1>
            </div>
            {viewToggle}
          </div>
          <LabelListView />
        </>
      ) : (
        <LabelGraphPage viewToggle={viewToggle} />
      )}
    </div>
  )
}

function LabelListView() {
  const user = useAuthStore((s) => s.user)
  const [labels, setLabels] = useState<LabelResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchLabels()
      .then(setLabels)
      .catch((err: unknown) => {
        if (err instanceof HTTPError && err.response.status === 401) {
          setError('Session expired. Please log in again.')
        } else {
          setError('Failed to load labels. Please try again later.')
        }
      })
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return <LoadingSpinner />
  }

  if (error !== null) {
    return (
      <div className="text-center py-24">
        <p className="text-red-600">{error}</p>
      </div>
    )
  }

  if (labels.length === 0) {
    return <p className="text-muted text-center py-16">No labels defined yet.</p>
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      {labels.map((label, i) => (
        <div
          key={label.id}
          className={`group relative p-5 rounded-xl border border-border bg-paper
                    hover:border-accent/40 hover:shadow-sm transition-all
                    opacity-0 animate-slide-up stagger-${Math.min(i + 1, 8)}`}
        >
          <Link
            to={`/labels/${label.id}`}
            className="absolute inset-0 rounded-xl"
            aria-label={`Open label #${label.id}`}
          />
          <div className="relative pointer-events-none">
            <div className="flex items-start justify-between">
              <div>
                <h3 className="font-display text-lg text-ink group-hover:text-accent transition-colors">
                  #{label.id}
                </h3>
                {label.names.length > 0 && (
                  <p className="text-sm text-muted mt-1">{label.names.join(', ')}</p>
                )}
              </div>
              <span className="text-xs font-mono text-muted bg-paper-warm px-2 py-1 rounded-md">
                {label.post_count} {label.post_count === 1 ? 'post' : 'posts'}
              </span>
            </div>

            {label.parents.length > 0 && (
              <div className="mt-3 flex items-center gap-1 text-xs text-muted">
                <span>{label.parents.length === 1 ? 'Parent:' : 'Parents:'}</span>
                {label.parents.map((p) => (
                  <span key={p} className="text-tag-text bg-tag-bg px-1.5 py-0.5 rounded">
                    #{p}
                  </span>
                ))}
              </div>
            )}
          </div>

          {user && (
            <Link
              to={`/labels/${label.id}/settings`}
              className="relative z-10 pointer-events-auto mt-3 inline-flex items-center
                       gap-1 text-xs text-muted hover:text-ink transition-colors
                       rounded-lg hover:bg-paper-warm p-1 -ml-1"
              aria-label={`Settings for ${label.id}`}
            >
              <Settings size={12} />
              <span>Settings</span>
            </Link>
          )}
        </div>
      ))}
    </div>
  )
}
