import useSWR from 'swr'
import type { SWRConfiguration } from 'swr'

/**
 * Typed wrapper around useSWR that uses the global fetcher from SWRConfig.
 * Keys are ky-relative URL paths (e.g., 'labels', 'posts/my-slug').
 * Pass null as key to suppress fetching.
 */
export function useSWRFetch<T>(key: string | null, options?: SWRConfiguration<T, Error>) {
  return useSWR<T, Error>(key, options)
}
