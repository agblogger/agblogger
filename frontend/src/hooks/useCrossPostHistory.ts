import useSWR from 'swr'
import { fetchCrossPostHistory } from '@/api/crosspost'
import type { CrossPostHistory } from '@/api/crosspost'

export function useCrossPostHistory(filePath: string | null) {
  return useSWR<CrossPostHistory, Error>(
    filePath !== null ? ['crossPostHistory', filePath] : null,
    ([, fp]: [string, string]) => fetchCrossPostHistory(fp),
  )
}
