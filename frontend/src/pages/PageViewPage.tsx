import { useEffect, useState } from 'react'
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
    return (
      <div className="flex items-center justify-center py-24" role="status" aria-label="Loading">
        <div className="w-6 h-6 border-2 border-accent/30 border-t-accent rounded-full animate-spin" />
      </div>
    )
  }

  if (error !== null || page === null) {
    return (
      <div className="text-center py-24">
        <p className="text-red-600">{error ?? 'Page not found'}</p>
      </div>
    )
  }

  return (
    <div className="animate-fade-in">
      <h1 className="font-display text-4xl text-ink mb-8">{page.title}</h1>
      <div
        className="prose max-w-none"
        dangerouslySetInnerHTML={{
          __html: renderedHtml.replace(/<h1[^>]*>[\s\S]*?<\/h1>\s*/i, ''),
        }}
      />
    </div>
  )
}
