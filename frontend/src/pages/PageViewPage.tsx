import { useEffect } from 'react'
import LoadingSpinner from '@/components/LoadingSpinner'
import { useParams } from 'react-router-dom'
import { useRenderedHtml } from '@/hooks/useKatex'
import { usePage } from '@/hooks/usePage'
import { useSiteStore } from '@/stores/siteStore'

export default function PageViewPage() {
  const { pageId } = useParams()
  const { data: page, error: pageErr, isLoading: loading } = usePage(pageId ?? null)
  const error = pageErr ? 'Failed to load page.' : null
  const renderedHtml = useRenderedHtml(page?.rendered_html)
  const siteTitle = useSiteStore((s) => s.config?.title)

  useEffect(() => {
    if (page !== undefined && siteTitle !== undefined && siteTitle !== '') {
      document.title = `${page.title} — ${siteTitle}`
    }
  }, [page, siteTitle])

  if (loading) {
    return <LoadingSpinner />
  }

  if (error !== null || page == null) {
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
