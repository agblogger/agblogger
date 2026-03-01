import { useEffect, useState } from 'react'
import { useSearchParams, Link } from 'react-router-dom'
import { Search } from 'lucide-react'
import { format, parseISO } from 'date-fns'
import { searchPosts } from '@/api/posts'
import type { SearchResult } from '@/api/client'
import { useRenderedHtml } from '@/hooks/useKatex'

export default function SearchPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const query = searchParams.get('q') ?? ''
  const [inputValue, setInputValue] = useState(query)
  const [results, setResults] = useState<SearchResult[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setInputValue(query)
  }, [query])

  function handleSearchSubmit(e: React.FormEvent) {
    e.preventDefault()
    const trimmed = inputValue.trim()
    if (trimmed.length > 0) {
      setSearchParams({ q: trimmed })
    }
  }

  useEffect(() => {
    if (!query.trim()) {
      setResults([])
      setError(null)
      return
    }
    void (async () => {
      setLoading(true)
      setError(null)
      try {
        const r = await searchPosts(query)
        setResults(r)
      } catch (err) {
        console.error('Search failed:', err)
        setError('Search failed. Please try again.')
      } finally {
        setLoading(false)
      }
    })()
  }, [query])

  return (
    <div className="animate-fade-in">
      <div className="mb-8">
        <form onSubmit={handleSearchSubmit} className="flex items-center gap-3">
          <Search size={20} className="text-muted shrink-0" />
          <input
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            placeholder="Search posts..."
            className="flex-1 px-3 py-1.5 text-sm bg-paper-warm border border-border rounded-lg
                     font-body text-ink placeholder:text-muted
                     focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/20"
          />
          <button
            type="submit"
            disabled={!inputValue.trim() || loading}
            className="px-3 py-1.5 text-sm font-medium bg-accent text-white rounded-lg
                     hover:bg-accent-light disabled:opacity-50 transition-colors"
          >
            Search
          </button>
        </form>
        {query.length > 0 && results.length > 0 && !loading && (
          <p className="mt-3 text-sm text-muted">
            {results.length} result{results.length !== 1 ? 's' : ''} for{' '}
            <span className="italic text-accent">&ldquo;{query}&rdquo;</span>
          </p>
        )}
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-16" role="status" aria-label="Loading">
          <div className="w-6 h-6 border-2 border-accent/30 border-t-accent rounded-full animate-spin" />
        </div>
      ) : error !== null ? (
        <p className="text-red-600 text-center py-16">{error}</p>
      ) : results.length === 0 ? (
        <p className="text-muted text-center py-16">
          {query ? 'No results found.' : 'Enter a search query above.'}
        </p>
      ) : (
        <div className="space-y-1">
          {results.map((result, i) => (
            <SearchResultItem key={result.id} result={result} index={i} />
          ))}
        </div>
      )}
    </div>
  )
}

function formatDate(dateStr: string): string {
  try {
    const parsed = parseISO(dateStr.replace(' ', 'T').replace(/([+-])(\d{2})$/, '$1$2:00'))
    return format(parsed, 'MMM d, yyyy')
  } catch {
    return dateStr.split(' ')[0] ?? ''
  }
}

function SearchResultItem({ result, index }: { result: SearchResult; index: number }) {
  const renderedExcerpt = useRenderedHtml(result.rendered_excerpt)

  return (
    <Link
      to={`/post/${result.file_path}`}
      className={`block py-4 px-4 -mx-4 rounded-xl hover:bg-paper-warm/60 transition-colors
                opacity-0 animate-slide-up stagger-${Math.min(index + 1, 8)}`}
    >
      <h3 className="font-display text-lg text-ink">{result.title}</h3>
      {renderedExcerpt && (
        <div
          className="text-sm text-muted mt-1 line-clamp-2 prose-excerpt"
          dangerouslySetInnerHTML={{ __html: renderedExcerpt }}
        />
      )}
      <span className="text-xs text-muted font-mono mt-2 block">
        {formatDate(result.created_at)}
      </span>
    </Link>
  )
}
