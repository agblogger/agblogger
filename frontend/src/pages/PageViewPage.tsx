import LoadingSpinner from '@/components/LoadingSpinner'
import RenderedContent from '@/components/RenderedContent'
import { useParams } from 'react-router-dom'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { usePage } from '@/hooks/usePage'

export default function PageViewPage() {
  const { pageId } = useParams()
  const { data: page, error: pageErr, isLoading: loading } = usePage(pageId ?? null)
  const error = pageErr ? 'Failed to load page.' : null
  useDocumentTitle(page?.title)

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
      <RenderedContent html={page.rendered_html} stripFirstH1 />
    </div>
  )
}
