import { useEffect, useMemo, useState } from 'react'
import { X, Calendar, User, Tag } from 'lucide-react'
import { fetchLabels } from '@/api/labels'
import { filterLabelsBySearch } from '@/components/labels/searchUtils'
import { useFilterPanelStore } from '@/stores/filterPanelStore'
import type { LabelResponse } from '@/api/client'

export interface FilterState {
  labels: string[]
  labelMode: 'or' | 'and'
  includeSublabels: boolean
  author: string
  fromDate: string
  toDate: string
}

const EMPTY_FILTER: FilterState = {
  labels: [],
  labelMode: 'or',
  includeSublabels: false,
  author: '',
  fromDate: '',
  toDate: '',
}

interface FilterPanelProps {
  value: FilterState
  onChange: (f: FilterState) => void
}

export default function FilterPanel({ value, onChange }: FilterPanelProps) {
  const panelState = useFilterPanelStore((s) => s.panelState)
  const closePanel = useFilterPanelStore((s) => s.closePanel)
  const onAnimationEnd = useFilterPanelStore((s) => s.onAnimationEnd)
  const setActiveFilterCount = useFilterPanelStore((s) => s.setActiveFilterCount)

  const [allLabels, setAllLabels] = useState<LabelResponse[]>([])
  const [labelSearch, setLabelSearch] = useState('')

  const expanded = panelState === 'open'

  useEffect(() => {
    fetchLabels().then(setAllLabels).catch(console.error)
  }, [])

  useEffect(() => {
    const count =
      value.labels.length +
      (value.author ? 1 : 0) +
      (value.fromDate ? 1 : 0) +
      (value.toDate ? 1 : 0)
    setActiveFilterCount(count)
  }, [value.labels.length, value.author, value.fromDate, value.toDate, setActiveFilterCount])

  const hasActive =
    value.labels.length > 0 || value.author !== '' || value.fromDate !== '' || value.toDate !== ''

  const filteredLabels = useMemo(
    () => filterLabelsBySearch(allLabels, labelSearch),
    [allLabels, labelSearch],
  )

  function toggleLabel(id: string) {
    const next = value.labels.includes(id)
      ? value.labels.filter((l) => l !== id)
      : [...value.labels, id]
    onChange({ ...value, labels: next })
  }

  function clearAll() {
    onChange(EMPTY_FILTER)
  }

  return (
    <div className="mb-6">
      {/* Active filter chips (always visible) */}
      {hasActive && !expanded && (
        <div className="flex items-center gap-2 mt-2 flex-wrap">
          {value.labels.map((l) => (
            <span
              key={l}
              className="inline-flex items-center gap-1 px-2 py-0.5 bg-tag-bg text-tag-text text-xs rounded-md"
            >
              #{l}
              <button onClick={() => toggleLabel(l)} className="hover:text-accent">
                <X size={10} />
              </button>
            </span>
          ))}
          {value.author && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-tag-bg text-tag-text text-xs rounded-md">
              {value.author}
              <button onClick={() => onChange({ ...value, author: '' })} className="hover:text-accent">
                <X size={10} />
              </button>
            </span>
          )}
          {(value.fromDate || value.toDate) && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-tag-bg text-tag-text text-xs rounded-md">
              {value.fromDate || '...'} - {value.toDate || '...'}
              <button onClick={() => onChange({ ...value, fromDate: '', toDate: '' })} className="hover:text-accent">
                <X size={10} />
              </button>
            </span>
          )}
          <button onClick={clearAll} className="text-xs text-accent hover:underline">
            Clear all
          </button>
        </div>
      )}

      {/* Expanded panel with slide/fade animation */}
      <div
        className="filter-panel-grid mt-3"
        data-state={panelState}
        onAnimationEnd={onAnimationEnd}
      >
        <div className="filter-panel-inner">
          <div className="p-4 border border-border rounded-xl bg-paper-warm/40 space-y-5">
            {/* Labels section */}
            <div>
              <div className="flex items-center gap-1.5 text-xs font-mono text-muted uppercase tracking-wider mb-2">
                <Tag size={12} />
                Labels
                <label className="normal-case tracking-normal font-body opacity-70 flex items-center gap-1 ml-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={value.includeSublabels}
                    onChange={(e) => onChange({ ...value, includeSublabels: e.target.checked })}
                    className="accent-accent"
                  />
                  incl. sub-labels
                </label>
              </div>

              <div className="flex items-center gap-2 mb-2">
                <input
                  type="text"
                  value={labelSearch}
                  onChange={(e) => setLabelSearch(e.target.value)}
                  placeholder="Search labels..."
                  className="flex-1 text-sm px-2.5 py-1.5 border border-border rounded-md bg-paper
                    focus:outline-none focus:border-accent/50"
                />
                <div className="flex text-[11px] border border-border rounded-md overflow-hidden">
                  <button
                    onClick={() => onChange({ ...value, labelMode: 'or' })}
                    className={`px-2 py-1 transition-colors ${
                      value.labelMode === 'or' ? 'bg-accent text-white' : 'bg-paper text-muted hover:bg-paper-warm'
                    }`}
                  >
                    OR
                  </button>
                  <button
                    onClick={() => onChange({ ...value, labelMode: 'and' })}
                    className={`px-2 py-1 transition-colors ${
                      value.labelMode === 'and' ? 'bg-accent text-white' : 'bg-paper text-muted hover:bg-paper-warm'
                    }`}
                  >
                    AND
                  </button>
                </div>
              </div>

              <div className="flex flex-wrap gap-1.5 max-h-32 overflow-y-auto">
                {filteredLabels.map((label) => {
                  const active = value.labels.includes(label.id)
                  return (
                    <button
                      key={label.id}
                      onClick={() => toggleLabel(label.id)}
                      className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
                        active
                          ? 'bg-accent text-white'
                          : 'bg-tag-bg text-tag-text hover:bg-border'
                      }`}
                    >
                      #{label.id} <span className="opacity-60">({label.post_count})</span>
                    </button>
                  )
                })}
                {filteredLabels.length === 0 && (
                  <span className="text-xs text-muted py-2">No matching labels</span>
                )}
              </div>
            </div>

            {/* Date range */}
            <div>
              <div className="flex items-center gap-1.5 text-xs font-mono text-muted uppercase tracking-wider mb-2">
                <Calendar size={12} />
                Date range
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="date"
                  value={value.fromDate}
                  onChange={(e) => onChange({ ...value, fromDate: e.target.value })}
                  className="text-sm px-2.5 py-1.5 border border-border rounded-md bg-paper
                    focus:outline-none focus:border-accent/50"
                />
                <span className="text-muted text-xs">to</span>
                <input
                  type="date"
                  value={value.toDate}
                  onChange={(e) => onChange({ ...value, toDate: e.target.value })}
                  className="text-sm px-2.5 py-1.5 border border-border rounded-md bg-paper
                    focus:outline-none focus:border-accent/50"
                />
              </div>
            </div>

            {/* Author */}
            <div>
              <div className="flex items-center gap-1.5 text-xs font-mono text-muted uppercase tracking-wider mb-2">
                <User size={12} />
                Author
              </div>
              <input
                type="text"
                value={value.author}
                onChange={(e) => onChange({ ...value, author: e.target.value })}
                placeholder="Filter by author..."
                className="w-full max-w-xs text-sm px-2.5 py-1.5 border border-border rounded-md bg-paper
                  focus:outline-none focus:border-accent/50"
              />
            </div>

            {/* Actions */}
            <div className="flex items-center gap-3 pt-2 border-t border-border/50">
              <button
                onClick={clearAll}
                className="text-xs text-muted hover:text-ink transition-colors"
              >
                Clear all
              </button>
              <button
                onClick={closePanel}
                className="text-xs text-accent hover:underline ml-auto"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export { EMPTY_FILTER }
