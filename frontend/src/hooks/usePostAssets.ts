import useSWR from 'swr'
import { fetchPostAssets } from '@/api/posts'
import type { AssetListResponse } from '@/api/client'

export function usePostAssets(filePath: string | null, refreshToken = 0) {
  return useSWR<AssetListResponse, Error>(
    filePath !== null ? ['postAssets', filePath, refreshToken] : null,
    ([, fp]: [string, string, number]) => fetchPostAssets(fp),
  )
}
