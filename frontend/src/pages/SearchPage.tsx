import { useEffect, useState } from 'react'
import { useSearchParams, Link } from 'react-router-dom'
import { Search } from 'lucide-react'
import { searchPosts } from '@/api/posts'
import type { SearchResult } from '@/api/client'
import { useRenderedHtml } from '@/hooks/useKatex'
import { formatRelativeDate } from '@/utils/date'

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
      <Link to="/" className="text-sm text-muted hover:text-accent transition-colors mb-6 inline-block">
        &larr; Back to posts
      </Link>
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
        <div className="space-y-1" role="status" aria-label="Loading results">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="py-4 px-4 -mx-4 animate-pulse">
              <div className="h-5 bg-border/50 rounded w-3/5 mb-2" />
              <div className="h-3.5 bg-border/40 rounded w-full mb-1" />
              <div className="h-3.5 bg-border/40 rounded w-4/5 mb-3" />
              <div className="h-3 bg-border/30 rounded w-24" />
            </div>
          ))}
        </div>
      ) : error !== null ? (
        <p className="text-red-600 dark:text-red-400 text-center py-16">{error}</p>
      ) : results.length === 0 ? (
        <div className="text-center py-16">
          {query ? (
            <>
              <p className="text-muted">
                No results found for <span className="italic text-accent">&ldquo;{query}&rdquo;</span>
              </p>
              <p className="text-sm text-muted/70 mt-2">
                Try different keywords or check your spelling.
              </p>
            </>
          ) : (
            <p className="text-muted">Enter a search query above.</p>
          )}
        </div>
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
        {formatRelativeDate(result.created_at)}
      </span>
    </Link>
  )
}
