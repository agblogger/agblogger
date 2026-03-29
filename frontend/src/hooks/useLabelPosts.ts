import { useState } from 'react'
import useSWR from 'swr'
import { fetchLabel, fetchLabelPosts } from '@/api/labels'
import type { LabelResponse, PostListResponse } from '@/api/client'
import { useAuthStore } from '@/stores/authStore'
import { readPreloaded } from '@/utils/preload'

interface LabelPostsData {
  label: LabelResponse
  posts: PostListResponse
}

export function useLabelPosts(labelId: string | null) {
  // Lazy initializer: reads and removes the preloaded script tag once per mount.
  // Returns null on subsequent mounts (tag already gone) — safe for SWR fallbackData.
  const [fallback] = useState<LabelPostsData | null>(() => {
    const data = readPreloaded({
      listHtml: {
        path: 'posts.posts',
        key: 'id',
        field: 'rendered_excerpt',
        itemSelector: '[data-id]',
        contentSelector: '[data-excerpt]',
      },
    })
    return data as LabelPostsData | null
  })

  const userId = useAuthStore((state) => state.user?.id ?? null)

  return useSWR<LabelPostsData, Error>(
    labelId !== null ? ['labelPosts', labelId, userId] : null,
    async ([, id]: [string, string, number | null]) => {
      const [label, posts] = await Promise.all([fetchLabel(id), fetchLabelPosts(id)])
      return { label, posts }
    },
    fallback !== null ? { fallbackData: fallback } : undefined,
  )
}
