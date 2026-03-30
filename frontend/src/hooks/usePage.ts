import useSWR from 'swr'
import type { SWRConfiguration } from 'swr'
import type { PageResponse } from '@/api/client'
import { useScopedPreloadedFallback } from '@/hooks/useScopedPreloadedFallback'
import { readPreloaded } from '@/utils/preload'

/** Uses the global fetcher from SWRConfig. Key: pages/${pageId} */
export function usePage(pageId: string | null) {
  const key = pageId !== null ? `pages/${pageId}` : null

  // Lazy initializer: reads and removes the preloaded script tag once per mount.
  // Returns null on subsequent mounts (tag already gone) — safe for SWR fallbackData.
  const fallback = useScopedPreloadedFallback<PageResponse>(key, () => {
    const raw = readPreloaded({
      html: { field: 'rendered_html', selector: '[data-content]' },
    })
    const data = raw && typeof raw === 'object' && 'title' in raw ? (raw as unknown as PageResponse) : null
    return data
  })

  const config: SWRConfiguration<PageResponse, Error> | undefined =
    fallback !== null ? { fallbackData: fallback } : undefined

  return useSWR<PageResponse, Error>(
    key,
    config,
  )
}
