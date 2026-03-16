import type { SearchResult } from '@/api/client'
import { formatRelativeDate } from '@/utils/date'
import { highlightMatch } from './highlightMatch'

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
          const highlighted = highlightMatch(result.title, query)
          const hasHighlight = highlighted.includes('<mark>')
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
                {hasHighlight && (
                  <span
                    aria-hidden="true"
                    // nosemgrep: typescript.react.security.audit.react-dangerouslysetinnerhtml
                    // Safe: title text is HTML-escaped by highlightMatch before mark tags are
                    // inserted. Output is only used as element innerHTML, never in attributes.
                    dangerouslySetInnerHTML={{ __html: highlighted }}
                  />
                )}
                <span className={hasHighlight ? 'sr-only' : ''}>{result.title}</span>
              </div>
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
