import useSWR from 'swr'
import { fetchLabel, fetchLabelPosts } from '@/api/labels'
import type { LabelResponse, PostListResponse } from '@/api/client'
import { useScopedPreloadedFallback } from '@/hooks/useScopedPreloadedFallback'
import { useAuthStore } from '@/stores/authStore'
import { readPreloaded } from '@/utils/preload'

interface LabelPostsData {
  label: LabelResponse
  posts: PostListResponse
}

export function useLabelPosts(labelId: string | null) {
  const userId = useAuthStore((state) => state.user?.id ?? null)
  const key = labelId !== null ? ['labelPosts', labelId, userId] as const : null

  const fallback = useScopedPreloadedFallback<LabelPostsData>(key, () => {
    const raw = readPreloaded({
      listHtml: {
        path: 'posts.posts',
        key: 'id',
        field: 'rendered_excerpt',
        itemSelector: '[data-id]',
        contentSelector: '[data-excerpt]',
      },
    })
    return raw !== null && 'posts' in raw ? (raw as unknown as LabelPostsData) : null
  })

  return useSWR<LabelPostsData, Error>(
    key,
    async ([, id]: [string, string, number | null]) => {
      const [label, posts] = await Promise.all([fetchLabel(id), fetchLabelPosts(id)])
      return { label, posts }
    },
    fallback !== null ? { fallbackData: fallback } : undefined,
  )
}
