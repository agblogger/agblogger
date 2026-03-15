import api from './client'
import type {
  AssetInfo,
  AssetListResponse,
  PostDetail,
  PostEditResponse,
  PostListResponse,
  SearchResult,
} from './client'

export interface PostListParams {
  page?: number
  per_page?: number
  label?: string
  labels?: string
  labelMode?: 'or' | 'and'
  includeSublabels?: boolean
  author?: string
  from?: string
  to?: string
  sort?: 'created_at' | 'modified_at' | 'title' | 'author'
  order?: 'asc' | 'desc'
}

export async function fetchPosts(params: PostListParams = {}): Promise<PostListResponse> {
  const searchParams = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null) {
      searchParams.set(key, String(value))
    }
  }
  return api.get('posts', { searchParams }).json<PostListResponse>()
}

export async function fetchPost(filePath: string): Promise<PostDetail> {
  return api.get(`posts/${filePath}`).json<PostDetail>()
}

export async function fetchPostForEdit(filePath: string): Promise<PostEditResponse> {
  return api.get(`posts/${filePath}/edit`).json<PostEditResponse>()
}

export async function searchPosts(query: string, limit = 20): Promise<SearchResult[]> {
  return api
    .get('posts/search', { searchParams: { q: query, limit: String(limit) } })
    .json<SearchResult[]>()
}

export async function createPost(params: {
  title: string
  body: string
  labels: string[]
  is_draft: boolean
}): Promise<PostDetail> {
  return api.post('posts', { json: params }).json<PostDetail>()
}

export async function updatePost(
  filePath: string,
  params: { title: string; body: string; labels: string[]; is_draft: boolean },
): Promise<PostDetail> {
  return api.put(`posts/${filePath}`, { json: params }).json<PostDetail>()
}

export async function deletePost(filePath: string, deleteAssets = false): Promise<void> {
  const searchParams = deleteAssets ? { delete_assets: 'true' } : undefined
  await api.delete(`posts/${filePath}`, { searchParams })
}

export async function uploadPost(files: File[], title?: string): Promise<PostDetail> {
  const form = new FormData()
  for (const file of files) {
    form.append('files', file)
  }
  const searchParams = title !== undefined && title.length > 0 ? { title } : undefined
  return api.post('posts/upload', { body: form, searchParams }).json<PostDetail>()
}

export async function uploadAssets(
  filePath: string,
  files: File[],
): Promise<{ uploaded: string[] }> {
  const form = new FormData()
  for (const file of files) {
    form.append('files', file)
  }
  return api.post(`posts/${filePath}/assets`, { body: form }).json<{ uploaded: string[] }>()
}

export async function fetchPostAssets(filePath: string): Promise<AssetListResponse> {
  return api.get(`posts/${filePath}/assets`).json<AssetListResponse>()
}

export async function deletePostAsset(filePath: string, filename: string): Promise<void> {
  await api.delete(`posts/${filePath}/assets/${encodeURIComponent(filename)}`)
}

export async function renamePostAsset(
  filePath: string,
  filename: string,
  newName: string,
): Promise<AssetInfo> {
  return api
    .patch(`posts/${filePath}/assets/${encodeURIComponent(filename)}`, {
      json: { new_name: newName },
    })
    .json<AssetInfo>()
}
