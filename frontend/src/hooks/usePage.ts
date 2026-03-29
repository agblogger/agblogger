import useSWR from 'swr'
import type { PageResponse } from '@/api/client'
import { readPreloadedData } from '@/utils/preload'

const preloaded = readPreloadedData<PageResponse>()

/** Uses the global fetcher from SWRConfig. Key: pages/${pageId} */
export function usePage(pageId: string | null) {
  return useSWR<PageResponse, Error>(
    pageId !== null ? `pages/${pageId}` : null,
    undefined,
    preloaded !== null ? { fallbackData: preloaded } : undefined,
  )
}
