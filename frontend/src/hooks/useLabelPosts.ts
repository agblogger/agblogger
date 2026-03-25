import useSWR from 'swr'
import { fetchLabel, fetchLabelPosts } from '@/api/labels'
import type { LabelResponse, PostListResponse } from '@/api/client'

interface LabelPostsData {
  label: LabelResponse
  posts: PostListResponse
}

export function useLabelPosts(labelId: string | null) {
  return useSWR<LabelPostsData, Error>(
    labelId !== null ? ['labelPosts', labelId] : null,
    async ([, id]: [string, string]) => {
      const [label, posts] = await Promise.all([fetchLabel(id), fetchLabelPosts(id)])
      return { label, posts }
    },
  )
}
