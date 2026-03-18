import { useEffect, useState } from 'react'
import LoadingSpinner from '@/components/LoadingSpinner'
import { useParams } from 'react-router-dom'
import api from '@/api/client'
import { useRenderedHtml } from '@/hooks/useKatex'
import type { PageResponse } from '@/api/client'

export default function PageViewPage() {
  const { pageId } = useParams()
  const [page, setPage] = useState<PageResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const renderedHtml = useRenderedHtml(page?.rendered_html)

  useEffect(() => {
    if (pageId === undefined) return
    void (async () => {
      setLoading(true)
      setError(null)
      try {
        const p = await api.get(`pages/${pageId}`).json<PageResponse>()
        setPage(p)
      } catch {
        setError('Failed to load page.')
      } finally {
        setLoading(false)
      }
    })()
  }, [pageId])

  if (loading) {
    return <LoadingSpinner />
  }

  if (error !== null || page === null) {
    return (
      <div className="text-center py-24">
        <p className="text-red-600 dark:text-red-400">{error ?? 'Page not found'}</p>
      </div>
    )
  }

  return (
    <div className="animate-fade-in">
      <h1 className="font-display text-4xl text-ink mb-8">{page.title}</h1>
      <div
        className="prose max-w-none"
        // nosemgrep: typescript.react.security.audit.react-dangerouslysetinnerhtml
        // Page HTML is rendered and sanitized server-side by the backend rendering pipeline.
        dangerouslySetInnerHTML={{
          __html: renderedHtml.replace(/<h1[^>]*>[\s\S]*?<\/h1>\s*/i, ''),
        }}
      />
    </div>
  )
}
