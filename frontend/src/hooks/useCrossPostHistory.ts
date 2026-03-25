import useSWR from 'swr'
import { fetchCrossPostHistory } from '@/api/crosspost'

export function useCrossPostHistory(filePath: string | null) {
  return useSWR(
    filePath !== null ? ['crossPostHistory', filePath] : null,
    ([, fp]: [string, string]) => fetchCrossPostHistory(fp),
  )
}
