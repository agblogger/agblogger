import useSWR from 'swr'
import { fetchLabels } from '@/api/labels'
import type { LabelResponse } from '@/api/client'

export function useLabels() {
  return useSWR<LabelResponse[], Error>('labels', fetchLabels)
}
