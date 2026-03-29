import useSWR from 'swr'
import { fetchPost } from '@/api/posts'
import { fetchViewCount } from '@/api/analytics'
import type { PostDetail, ViewCountResponse } from '@/api/client'
import { useAuthStore } from '@/stores/authStore'
import { readPreloadedData } from '@/utils/preload'

const preloaded = readPreloadedData<PostDetail>()

export function usePost(slug: string | null) {
  const userId = useAuthStore((state) => state.user?.id ?? null)

  return useSWR<PostDetail, Error>(
    slug !== null ? ['post', slug, userId] : null,
    ([, s]: [string, string, number | null]) => fetchPost(s),
    preloaded !== null ? { fallbackData: preloaded } : undefined,
  )
}

export function useViewCount(slug: string | null) {
  return useSWR<ViewCountResponse, Error>(
    slug !== null ? ['viewCount', slug] : null,
    ([, s]: [string, string]) => fetchViewCount(s),
  )
}
