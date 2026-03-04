import ky, { HTTPError } from 'ky'

const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])
const CSRF_HEADER_NAME = 'X-CSRF-Token'

let csrfToken: string | null = null
let csrfTokenRequest: Promise<string | null> | null = null

function setCachedCsrfToken(nextToken: string | null): void {
  csrfToken = nextToken !== null && nextToken.trim() !== '' ? nextToken : null
}

export function primeCsrfToken(nextToken: string): void {
  setCachedCsrfToken(nextToken)
}

export function clearCsrfToken(): void {
  csrfToken = null
  csrfTokenRequest = null
}

async function fetchCsrfToken(): Promise<string | null> {
  try {
    const response = await ky
      .get('auth/csrf', {
        prefixUrl: '/api',
        credentials: 'include',
      })
      .json<{ csrf_token: string }>()
    setCachedCsrfToken(response.csrf_token)
    return csrfToken
  } catch {
    clearCsrfToken()
    return null
  } finally {
    csrfTokenRequest = null
  }
}

async function getCsrfToken(): Promise<string | null> {
  if (csrfToken !== null) {
    return csrfToken
  }
  if (csrfTokenRequest !== null) {
    return csrfTokenRequest
  }
  csrfTokenRequest = fetchCsrfToken()
  return csrfTokenRequest
}

async function setCsrfHeader(headers: Headers): Promise<void> {
  const nextToken = await getCsrfToken()
  if (nextToken !== null) {
    headers.set(CSRF_HEADER_NAME, nextToken)
  }
}

async function refreshAccessToken(): Promise<boolean> {
  const headers = new Headers()
  await setCsrfHeader(headers)

  try {
    const response = await ky
      .post('auth/refresh', {
        prefixUrl: '/api',
        credentials: 'include',
        headers,
        json: {},
      })
      .json<SessionAuthResponse>()
    primeCsrfToken(response.csrf_token)
    return true
  } catch (err) {
    console.error('Token refresh failed:', err)
    clearCsrfToken()
    return false
  }
}

const api = ky.create({
  prefixUrl: '/api',
  credentials: 'include',
  hooks: {
    beforeRequest: [
      async (request) => {
        if (UNSAFE_METHODS.has(request.method)) {
          await setCsrfHeader(request.headers)
        }
      },
    ],
    afterResponse: [
      async (request, _options, response) => {
        const alreadyRetried = request.headers.get('X-Auth-Retry') === '1'
        if (response.status === 401 && !request.url.includes('/auth/refresh') && !alreadyRetried) {
          const refreshed = await refreshAccessToken()
          if (!refreshed) {
            return response
          }

          try {
            const headers = new Headers(request.headers)
            headers.set('X-Auth-Retry', '1')
            if (UNSAFE_METHODS.has(request.method)) {
              await setCsrfHeader(headers)
            }
            const retryRequest = new Request(request, { headers })
            return await ky(retryRequest, {
              credentials: 'include',
              retry: 0,
            })
          } catch (retryErr) {
            console.error('Request retry after refresh failed:', retryErr)
            return response
          }
        }
        return response
      },
    ],
  },
})

export default api

export { HTTPError }

// Type definitions
export interface PostSummary {
  id: number
  file_path: string
  title: string
  author: string | null
  created_at: string
  modified_at: string
  is_draft: boolean
  rendered_excerpt: string | null
  labels: string[]
}

export interface PostDetail extends PostSummary {
  rendered_html: string
  content: string | null
}

export interface PostListResponse {
  posts: PostSummary[]
  total: number
  page: number
  per_page: number
  total_pages: number
}

export interface LabelResponse {
  id: string
  names: string[]
  is_implicit: boolean
  parents: string[]
  children: string[]
  post_count: number
}

export interface LabelGraphNode {
  id: string
  names: string[]
  post_count: number
}

export interface LabelGraphEdge {
  source: string
  target: string
}

export interface LabelGraphResponse {
  nodes: LabelGraphNode[]
  edges: LabelGraphEdge[]
}

export interface LabelCreateRequest {
  id: string
  names?: string[]
  parents?: string[]
}

export interface LabelUpdateRequest {
  names: string[]
  parents: string[]
}

export interface LabelDeleteResponse {
  id: string
  deleted: boolean
}

export interface PageConfig {
  id: string
  title: string
  file: string | null
}

export interface SiteConfigResponse {
  title: string
  description: string
  pages: PageConfig[]
}

export interface PageResponse {
  id: string
  title: string
  rendered_html: string
}

export interface SessionAuthResponse {
  csrf_token: string
}

export interface UserResponse {
  id: number
  username: string
  email: string
  display_name: string | null
  is_admin: boolean
}

export interface SearchResult {
  id: number
  file_path: string
  title: string
  rendered_excerpt: string | null
  created_at: string
  rank: number
}

export interface PostEditResponse {
  file_path: string
  title: string
  body: string
  labels: string[]
  is_draft: boolean
  created_at: string
  modified_at: string
  author: string | null
}

export interface AdminSiteSettings {
  title: string
  description: string
  default_author: string
  timezone: string
}

export interface AdminPageConfig {
  id: string
  title: string
  file: string | null
  is_builtin: boolean
  content: string | null
}

export interface AdminPagesResponse {
  pages: AdminPageConfig[]
}
