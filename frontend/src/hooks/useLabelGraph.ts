import useSWR from 'swr'
import { fetchLabelGraph } from '@/api/labels'
import type { LabelGraphResponse } from '@/api/client'
import { useAuthStore } from '@/stores/authStore'

export function useLabelGraph() {
  const userId = useAuthStore((state) => state.user?.id ?? null)

  return useSWR<LabelGraphResponse, Error>(
    ['labels/graph', userId],
    async () => fetchLabelGraph(),
  )
}
