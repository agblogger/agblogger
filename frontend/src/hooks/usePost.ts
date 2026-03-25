import useSWR from 'swr'
import { fetchPost } from '@/api/posts'
import { fetchViewCount } from '@/api/analytics'
import type { PostDetail, ViewCountResponse } from '@/api/client'

export function usePost(slug: string | null) {
  return useSWR<PostDetail>(
    slug !== null ? ['post', slug] : null,
    ([, s]: [string, string]) => fetchPost(s),
  )
}

export function useViewCount(slug: string | null) {
  return useSWR<ViewCountResponse>(
    slug !== null ? ['viewCount', slug] : null,
    ([, s]: [string, string]) => fetchViewCount(s),
  )
}
