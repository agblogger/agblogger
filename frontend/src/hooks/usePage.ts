import useSWR from 'swr'
import type { SWRConfiguration } from 'swr'
import type { PageResponse } from '@/api/client'
import { useScopedPreloadedFallback } from '@/hooks/useScopedPreloadedFallback'
import { readPreloaded } from '@/utils/preload'

/** Uses the global fetcher from SWRConfig. Key: pages/${pageId} */
export function usePage(pageId: string | null) {
  const key = pageId !== null ? `pages/${pageId}` : null

  const fallback = useScopedPreloadedFallback<PageResponse>(key, () => {
    const raw = readPreloaded({
      html: { field: 'rendered_html', selector: '[data-content]' },
    })
    return raw !== null && 'title' in raw ? (raw as unknown as PageResponse) : null
  })

  const config: SWRConfiguration<PageResponse, Error> | undefined =
    fallback !== null ? { fallbackData: fallback } : undefined

  return useSWR<PageResponse, Error>(
    key,
    config,
  )
}
