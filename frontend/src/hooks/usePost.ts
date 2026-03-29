import { useState } from 'react'
import useSWR from 'swr'
import { fetchPost } from '@/api/posts'
import { fetchViewCount } from '@/api/analytics'
import type { PostDetail, ViewCountResponse } from '@/api/client'
import { useAuthStore } from '@/stores/authStore'
import { readPreloaded } from '@/utils/preload'

export function usePost(slug: string | null) {
  // Lazy initializer: reads and removes the preloaded script tag once per mount.
  // Returns null on subsequent mounts (tag already gone) — safe for SWR fallbackData.
  const [fallback] = useState<PostDetail | null>(() => {
    const data = readPreloaded({
      html: { field: 'rendered_html', selector: '[data-content]' },
    })
    return data as PostDetail | null
  })

  const userId = useAuthStore((state) => state.user?.id ?? null)

  return useSWR<PostDetail, Error>(
    slug !== null ? ['post', slug, userId] : null,
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
