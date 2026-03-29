import { useState } from 'react'
import useSWR from 'swr'
import type { SWRConfiguration } from 'swr'
import type { PageResponse } from '@/api/client'
import { readPreloaded } from '@/utils/preload'

/** Uses the global fetcher from SWRConfig. Key: pages/${pageId} */
export function usePage(pageId: string | null) {
  // Lazy initializer: reads and removes the preloaded script tag once per mount.
  // Returns null on subsequent mounts (tag already gone) — safe for SWR fallbackData.
  const [fallback] = useState<PageResponse | null>(() => {
    const data = readPreloaded({
      html: { field: 'rendered_html', selector: '[data-content]' },
    })
    return data as PageResponse | null
  })

  const config: SWRConfiguration<PageResponse, Error> | undefined =
    fallback !== null ? { fallbackData: fallback } : undefined

  return useSWR<PageResponse, Error>(
    pageId !== null ? `pages/${pageId}` : null,
    config,
  )
}
