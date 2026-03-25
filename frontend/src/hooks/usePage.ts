import useSWR from 'swr'
import type { PageResponse } from '@/api/client'

/** Uses the global fetcher from SWRConfig. Key: pages/${pageId} */
export function usePage(pageId: string | null) {
  return useSWR<PageResponse>(pageId !== null ? `pages/${pageId}` : null)
}
