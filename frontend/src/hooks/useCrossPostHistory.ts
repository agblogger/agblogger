import useSWR from 'swr'
import { fetchCrossPostHistory } from '@/api/crosspost'
import type { CrossPostHistory } from '@/api/crosspost'
import { useAuthStore } from '@/stores/authStore'

export function useCrossPostHistory(filePath: string | null) {
  const userId = useAuthStore((state) => state.user?.id ?? null)

  return useSWR<CrossPostHistory, Error>(
    filePath !== null && userId !== null ? ['crossPostHistory', filePath, userId] : null,
    ([, fp]: [string, string, number]) => fetchCrossPostHistory(fp),
  )
}
