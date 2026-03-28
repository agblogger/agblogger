import useSWR from 'swr'
import { fetchLabels } from '@/api/labels'
import type { LabelResponse } from '@/api/client'
import { useAuthStore } from '@/stores/authStore'

export function useLabels() {
  const userId = useAuthStore((state) => state.user?.id ?? null)

  return useSWR<LabelResponse[], Error>(
    ['labels', userId],
    async () => fetchLabels(),
  )
}
