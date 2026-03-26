import type { SearchResult } from '@/api/client'
import { formatRelativeDate } from '@/utils/date'
import { highlightParts } from './highlightMatch'

interface SearchDropdownProps {
  results: SearchResult[]
  query: string
  highlightIndex: number
  onSelect: (filePath: string) => void
  onFooterClick: () => void
  error?: string | null
  loading?: boolean
}

export default function SearchDropdown({
  results,
  query,
  highlightIndex,
  onSelect,
  onFooterClick,
  error,
  loading,
}: SearchDropdownProps) {
  if (error != null) {
    return (
      <div
        className="absolute top-full left-0 right-0 mt-1 bg-paper border border-border
                   rounded-lg shadow-lg z-[60] overflow-hidden"
      >
        <div className="px-3 py-2 text-sm text-red-600 dark:text-red-400">{error}</div>
      </div>
    )
  }

  if (loading === true && results.length === 0) {
    return (
      <div
        className="absolute top-full left-0 right-0 mt-1 bg-paper border border-border
                   rounded-lg shadow-lg z-[60] overflow-hidden"
      >
        <div className="px-3 py-2 text-sm text-muted">Searching...</div>
      </div>
    )
  }

  if (results.length === 0) {
    return (
      <div
        className="absolute top-full left-0 right-0 mt-1 bg-paper border border-border
                   rounded-lg shadow-lg z-[60] overflow-hidden"
      >
        <div className="px-3 py-2 text-sm text-muted">No results found</div>
      </div>
    )
  }

  return (
    <div
      className="absolute top-full left-0 right-0 mt-1 bg-paper border border-border
                 rounded-lg shadow-lg z-[60] overflow-hidden"
    >
      <ul id="search-results-listbox" role="listbox">
        {results.map((result, i) => {
          const segments = highlightParts(result.title, query)
          return (
            <li
              key={result.id}
              id={`search-result-${i}`}
              role="option"
              aria-selected={i === highlightIndex}
              className={`px-3 py-2 cursor-pointer transition-colors ${
                i === highlightIndex ? 'bg-accent/10' : 'hover:bg-paper-warm'
              }`}
              onMouseDown={(e) => {
                e.preventDefault()
                onSelect(result.file_path)
              }}
            >
              <div className="text-sm font-medium text-ink truncate">
                {segments.map((seg, j) =>
                  seg.match ? <mark key={j}>{seg.text}</mark> : seg.text,
                )}
              </div>
              {result.subtitle != null && (
                <div className="text-xs text-ink/60 truncate">{result.subtitle}</div>
              )}
              <div className="text-xs text-muted mt-0.5">
                {formatRelativeDate(result.created_at)}
              </div>
            </li>
          )
        })}
      </ul>
      <div
        className="px-3 py-2 text-center border-t border-border cursor-pointer
                   hover:bg-paper-warm transition-colors"
        onMouseDown={(e) => {
          e.preventDefault()
          onFooterClick()
        }}
      >
        <span className="text-xs text-accent">View all results</span>
      </div>
    </div>
  )
}
