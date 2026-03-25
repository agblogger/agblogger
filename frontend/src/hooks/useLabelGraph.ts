import useSWR from 'swr'
import { fetchLabelGraph } from '@/api/labels'
import type { LabelGraphResponse } from '@/api/client'

export function useLabelGraph() {
  return useSWR<LabelGraphResponse, Error>('labels/graph', fetchLabelGraph)
}
