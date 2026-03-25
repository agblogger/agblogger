import { lazy, Suspense, useMemo, useState } from 'react'
import LoadingSpinner from '@/components/LoadingSpinner'
import { Link } from 'react-router-dom'
import { Tag, Settings, Search, Plus } from 'lucide-react'

import { useAuthStore } from '@/stores/authStore'
import { HTTPError } from '@/api/client'
import { useLabels } from '@/hooks/useLabels'
import { filterLabelsBySearch } from '@/components/labels/searchUtils'
import LabelChip from '@/components/labels/LabelChip'
import ParentLabelLinks from '@/components/labels/ParentLabelLinks'

const LabelGraphPage = lazy(() => import('@/pages/LabelGraphPage'))

export default function LabelsPage() {
  const user = useAuthStore((s) => s.user)
  const [view, setView] = useState<'list' | 'graph'>('list')
  const [search, setSearch] = useState('')

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
      <div className="flex flex-wrap items-center gap-3 mb-8">
        <div className="flex items-center gap-3">
          <Tag size={20} className="text-accent" />
          <h1 className="font-display text-3xl text-ink">Labels</h1>
        </div>
        <div className="flex flex-wrap items-center gap-3 ml-auto">
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Filter labels..."
              aria-label="Filter labels"
              className="w-48 pl-9 pr-3 py-2 text-sm border border-border rounded-lg
                bg-paper focus:outline-none focus:border-accent/50 transition-colors"
            />
          </div>
          {viewToggle}
          {user?.is_admin === true && (
            <Link
              to="/labels/new"
              className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium
                       bg-accent text-white rounded-lg hover:bg-accent-light transition-colors"
            >
              <Plus size={16} />
              New Label
            </Link>
          )}
        </div>
      </div>

      {view === 'list' ? (
        <LabelListView search={search} />
      ) : (
        <Suspense fallback={<LoadingSpinner />}>
          <LabelGraphPage search={search} />
        </Suspense>
      )}
    </div>
  )
}

function LabelListView({ search }: { search: string }) {
  const user = useAuthStore((s) => s.user)
  const { data: labels = [], error, isLoading: loading } = useLabels()
  const errorMsg = error
    ? error instanceof HTTPError && error.response.status === 401
      ? 'Session expired. Please log in again.'
      : 'Failed to load labels. Please try again later.'
    : null

  const filteredLabels = useMemo(() => filterLabelsBySearch(labels, search), [labels, search])

  if (loading) {
    return <LoadingSpinner />
  }

  if (errorMsg !== null) {
    return (
      <div className="text-center py-24">
        <p className="text-red-600 dark:text-red-400">{errorMsg}</p>
      </div>
    )
  }

  if (labels.length === 0) {
    return <p className="text-muted text-center py-16">No labels defined yet.</p>
  }

  if (filteredLabels.length === 0) {
    return <p className="text-muted text-center py-16">No labels match your search.</p>
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      {filteredLabels.map((label, i) => (
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

            {label.children.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-1.5 pointer-events-auto relative z-10">
                {label.children.map((c) => (
                  <LabelChip key={c} labelId={c} />
                ))}
              </div>
            )}

            {label.parents.length > 0 && (
              <div className="mt-2 text-xs text-muted pointer-events-auto relative z-10">
                <span>in </span>
                <ParentLabelLinks parents={label.parents} stopPropagation />
              </div>
            )}
          </div>

          {user?.is_admin === true && (
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
