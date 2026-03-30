import { useEffect } from 'react'
import { useSiteStore } from '@/stores/siteStore'

/**
 * Set document.title to `pageTitle — siteTitle`, or just `siteTitle` when
 * no pageTitle is provided.  Does nothing while siteTitle is still loading.
 */
export function useDocumentTitle(pageTitle?: string) {
  const siteTitle = useSiteStore((s) => s.config?.title)
  useEffect(() => {
    if (siteTitle === undefined || siteTitle === '') return
    document.title = pageTitle !== undefined && pageTitle !== '' ? `${pageTitle} — ${siteTitle}` : siteTitle
  }, [pageTitle, siteTitle])
}
