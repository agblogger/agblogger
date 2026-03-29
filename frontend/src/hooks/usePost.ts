import useSWR from 'swr'
import { fetchPost } from '@/api/posts'
import { fetchViewCount } from '@/api/analytics'
import type { PostDetail, ViewCountResponse } from '@/api/client'
import { useScopedPreloadedFallback } from '@/hooks/useScopedPreloadedFallback'
import { useAuthStore } from '@/stores/authStore'
import { readPreloaded } from '@/utils/preload'

export function usePost(slug: string | null) {
  const userId = useAuthStore((state) => state.user?.id ?? null)
  const key = slug !== null ? ['post', slug, userId] as const : null

  // Lazy initializer: reads and removes the preloaded script tag once per mount.
  // Returns null on subsequent mounts (tag already gone) — safe for SWR fallbackData.
  const fallback = useScopedPreloadedFallback<PostDetail>(key, () => {
    const data = readPreloaded({
      html: { field: 'rendered_html', selector: '[data-content]' },
    })
    return data as PostDetail | null
  })

  return useSWR<PostDetail, Error>(
    key,
    ([, s]: [string, string, number | null]) => fetchPost(s),
    fallback !== null ? { fallbackData: fallback } : undefined,
  )
}

export function useViewCount(slug: string | null) {
  return useSWR<ViewCountResponse, Error>(
    slug !== null ? ['viewCount', slug] : null,
    ([, s]: [string, string]) => fetchViewCount(s),
  )
}
