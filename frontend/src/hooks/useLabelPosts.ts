import useSWR from 'swr'
import { fetchLabel, fetchLabelPosts } from '@/api/labels'
import type { LabelResponse, PostListResponse } from '@/api/client'
import { useAuthStore } from '@/stores/authStore'
import { readPreloaded } from '@/utils/preload'

interface LabelPostsData {
  label: LabelResponse
  posts: PostListResponse
}

const preloaded = readPreloaded<LabelPostsData>({
  listHtml: {
    path: 'posts.posts',
    key: 'id',
    field: 'rendered_excerpt',
    itemSelector: '[data-id]',
    contentSelector: '[data-excerpt]',
  },
})

export function useLabelPosts(labelId: string | null) {
  const userId = useAuthStore((state) => state.user?.id ?? null)

  return useSWR<LabelPostsData, Error>(
    labelId !== null ? ['labelPosts', labelId, userId] : null,
    async ([, id]: [string, string, number | null]) => {
      const [label, posts] = await Promise.all([fetchLabel(id), fetchLabelPosts(id)])
      return { label, posts }
    },
    preloaded !== null ? { fallbackData: preloaded } : undefined,
  )
}
