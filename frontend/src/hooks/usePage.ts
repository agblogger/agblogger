import useSWR from 'swr'
import type { PageResponse } from '@/api/client'
import { readPreloaded } from '@/utils/preload'

const preloaded = readPreloaded({
  html: { field: 'rendered_html', selector: '[data-content]' },
}) as PageResponse | null

/** Uses the global fetcher from SWRConfig. Key: pages/${pageId} */
export function usePage(pageId: string | null) {
  return useSWR<PageResponse, Error>(
    pageId !== null ? `pages/${pageId}` : null,
    preloaded !== null ? { fallbackData: preloaded } : undefined,
  )
}
