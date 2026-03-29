import { useEffect, useState, useCallback, useRef, useMemo } from 'react'
import { useSearchParams, useNavigate, Link } from 'react-router-dom'
import { ChevronLeft, ChevronRight, FileText, Upload } from 'lucide-react'
import AlertBanner from '@/components/AlertBanner'
import PostCard from '@/components/posts/PostCard'
import FilterPanel, { EMPTY_FILTER, type FilterState } from '@/components/filters/FilterPanel'
import { fetchPosts, uploadPost, type PostListParams } from '@/api/posts'
import { HTTPError } from '@/api/client'
import type { PostListResponse } from '@/api/client'
import { useAuthStore } from '@/stores/authStore'
import { postUrl } from '@/utils/postUrl'
import { localDateToUtcStart, localDateToUtcEnd } from '@/utils/date'
import { readPreloaded } from '@/utils/preload'

export default function TimelinePage() {
  // Lazy initializer: reads and removes the preloaded script tag once per mount.
  // Returns null on subsequent mounts (tag already gone).
  const [initialData] = useState<PostListResponse | null>(() => {
    const data = readPreloaded({
      listHtml: {
        path: 'posts',
        key: 'id',
        field: 'rendered_excerpt',
        itemSelector: '[data-id]',
        contentSelector: '[data-excerpt]',
      },
    })
    return data as PostListResponse | null
  })

  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const [data, setData] = useState<PostListResponse | null>(initialData)
  const [loading, setLoading] = useState(initialData === null)
  const [error, setError] = useState<string | null>(null)
  const [retryCount, setRetryCount] = useState(0)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [titlePrompt, setTitlePrompt] = useState<{ files: File[] } | null>(null)
  const [promptTitle, setPromptTitle] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)
  const folderInputRef = useRef<HTMLInputElement>(null)
  // Track whether the initial preloaded data has been consumed so the first useEffect
  // run can skip the network fetch when preloaded data is already shown.
  const consumedPreload = useRef(initialData !== null)

  // Parse filter state from URL
  const page = Number(searchParams.get('page') ?? '1')
  const urlLabelMode = searchParams.get('labelMode')
  const parsedLabelMode: 'or' | 'and' = urlLabelMode === 'and' ? 'and' : 'or'
  const filterState: FilterState = useMemo(() => ({
    labels: searchParams.get('labels')?.split(',').filter(Boolean) ?? [],
    labelMode: parsedLabelMode,
    includeSublabels: searchParams.get('includeSublabels') === 'true',
    author: searchParams.get('author') ?? '',
    fromDate: searchParams.get('from') ?? '',
    toDate: searchParams.get('to') ?? '',
  }), [searchParams, parsedLabelMode])

  // Sync filters to URL
  const setFilter = useCallback(
    (f: FilterState) => {
      const params = new URLSearchParams()
      if (f.labels.length > 0) params.set('labels', f.labels.join(','))
      if (f.labelMode !== 'or') params.set('labelMode', f.labelMode)
      if (f.includeSublabels) params.set('includeSublabels', 'true')
      if (f.author) params.set('author', f.author)
      if (f.fromDate) params.set('from', f.fromDate)
      if (f.toDate) params.set('to', f.toDate)
      // Reset page when filters change
      setSearchParams(params)
    },
    [setSearchParams],
  )

  useEffect(() => {
    // Skip the first fetch when preloaded data was used — it's already shown.
    // Subsequent runs (retryCount, user, searchParams changes) always fetch.
    if (consumedPreload.current) {
      consumedPreload.current = false
      return
    }

    const p = Number(searchParams.get('page') ?? '1')
    const labels = searchParams.get('labels')?.split(',').filter(Boolean) ?? []
    const labelModeParam = searchParams.get('labelMode')
    const labelMode: 'or' | 'and' = labelModeParam === 'and' ? 'and' : 'or'
    const includeSublabels = searchParams.get('includeSublabels') === 'true'
    const author = searchParams.get('author') ?? ''
    const fromDate = searchParams.get('from') ?? ''
    const toDate = searchParams.get('to') ?? ''

    void (async () => {
      setLoading(true)
      setError(null)
      try {
        const params: PostListParams = {
          page: p,
          per_page: 10,
        }
        if (labels.length > 0) params.labels = labels.join(',')
        if (labelMode !== 'or') params.labelMode = labelMode
        if (includeSublabels) params.includeSublabels = true
        if (author) params.author = author
        if (fromDate) params.from = localDateToUtcStart(fromDate)
        if (toDate) params.to = localDateToUtcEnd(toDate)
        const d = await fetchPosts(params)
        setData(d)
      } catch (err) {
        console.error('Failed to fetch posts:', err)
        setError('Failed to load posts. Please try again.')
      } finally {
        setLoading(false)
      }
    })()
  }, [searchParams, retryCount, user])

  function goToPage(p: number) {
    const params = new URLSearchParams(searchParams)
    params.set('page', String(p))
    setSearchParams(params)
  }

  async function handleUpload(files: FileList | File[]) {
    const fileArray = Array.from(files)
    if (fileArray.length === 0) return

    setUploading(true)
    setUploadError(null)
    try {
      const result = await uploadPost(fileArray)
      void navigate(postUrl(result.file_path))
    } catch (err) {
      if (err instanceof HTTPError) {
        if (err.response.status === 422) {
          const body: { detail: string } = await err.response.json()
          if (body.detail === 'no_title') {
            setTitlePrompt({ files: fileArray })
            setPromptTitle('')
            return
          }
          setUploadError(body.detail || 'Invalid file format.')
        } else if (err.response.status === 413) {
          setUploadError('File too large. Maximum size is 10 MB per file.')
        } else if (err.response.status === 401) {
          setUploadError('Session expired. Please log in again.')
        } else {
          setUploadError('Failed to upload post.')
        }
      } else {
        setUploadError('Failed to upload post.')
      }
    } finally {
      setUploading(false)
    }
  }

  async function handleTitleSubmit() {
    if (!titlePrompt || !promptTitle.trim()) return

    setUploading(true)
    setUploadError(null)
    try {
      const result = await uploadPost(titlePrompt.files, promptTitle.trim())
      setTitlePrompt(null)
      void navigate(postUrl(result.file_path))
    } catch {
      setUploadError('Failed to upload post.')
      setTitlePrompt(null)
    } finally {
      setUploading(false)
    }
  }

  return (
    <div>
      <input
        ref={fileInputRef}
        type="file"
        accept=".md,.markdown"
        className="hidden"
        onChange={(e) => {
          if (e.target.files) void handleUpload(e.target.files)
          e.target.value = ''
        }}
      />
      <input
        ref={folderInputRef}
        type="file"
        // @ts-expect-error webkitdirectory is not in React types
        webkitdirectory=""
        className="hidden"
        onChange={(e) => {
          if (e.target.files) void handleUpload(e.target.files)
          e.target.value = ''
        }}
      />

      <FilterPanel value={filterState} onChange={setFilter} />

      {user && (
        <div className="flex items-center gap-2 mb-4">
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium
                     text-muted border border-border rounded-lg
                     hover:text-ink hover:bg-paper-warm
                     disabled:opacity-50 transition-colors"
          >
            <Upload size={14} />
            {uploading ? 'Uploading...' : 'Upload file'}
          </button>
          <button
            onClick={() => folderInputRef.current?.click()}
            disabled={uploading}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium
                     text-muted border border-border rounded-lg
                     hover:text-ink hover:bg-paper-warm
                     disabled:opacity-50 transition-colors"
          >
            <Upload size={14} />
            {uploading ? 'Uploading...' : 'Upload folder'}
          </button>
          {uploading && (
            <div className="w-4 h-4 border-2 border-accent/30 border-t-accent rounded-full animate-spin" />
          )}
        </div>
      )}

      {uploadError !== null && (
        <AlertBanner variant="error" className="mb-4">{uploadError}</AlertBanner>
      )}

      {loading ? (
        <div className="divide-y divide-border/60" role="status" aria-label="Loading posts">
          {[0, 1, 2].map((i) => (
            <div key={i} className="py-6 animate-pulse">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0 space-y-3">
                  <div className="h-5 bg-border/50 rounded w-3/5" />
                  <div className="space-y-2">
                    <div className="h-3.5 bg-border/40 rounded w-full" />
                    <div className="h-3.5 bg-border/40 rounded w-4/5" />
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="h-3 bg-border/30 rounded w-20" />
                    <div className="h-3 bg-border/30 rounded w-16" />
                  </div>
                </div>
                <div className="hidden sm:block w-1 h-12 rounded-full bg-border/30 shrink-0 mt-1" />
              </div>
            </div>
          ))}
        </div>
      ) : error !== null ? (
        <div className="text-center py-24">
          <p className="font-display text-2xl text-red-600 dark:text-red-400">{error}</p>
          <button
            onClick={() => setRetryCount((c) => c + 1)}
            className="text-accent text-sm hover:underline mt-4"
          >
            Retry
          </button>
        </div>
      ) : !data || data.posts.length === 0 ? (
        <div className="text-center py-24">
          <FileText size={48} className="mx-auto text-muted/40 mb-4" />
          {filterState.labels.length > 0 || filterState.author || filterState.fromDate || filterState.toDate ? (
            <>
              <p className="font-display text-2xl text-muted italic">No posts found</p>
              <p className="text-sm text-muted mt-2">Try adjusting your filters.</p>
              <button
                onClick={() => setFilter(EMPTY_FILTER)}
                className="text-accent text-sm hover:underline mt-4"
              >
                Clear filters
              </button>
            </>
          ) : user ? (
            <>
              <p className="font-display text-2xl text-muted italic">No posts yet</p>
              <Link
                to="/editor/new"
                className="inline-block mt-4 px-5 py-2.5 text-sm font-medium text-white bg-accent hover:bg-accent-light rounded-lg transition-colors"
              >
                Write your first post
              </Link>
            </>
          ) : (
            <>
              <p className="font-display text-2xl text-muted italic">No posts yet</p>
              <p className="text-sm text-muted mt-2">Check back soon.</p>
            </>
          )}
        </div>
      ) : (
        <>
          <div className="divide-y divide-border/60">
            {data.posts.map((post, i) => (
              <PostCard key={post.id} post={post} index={i} />
            ))}
          </div>

          {data.total_pages > 1 && (
            <div className="flex items-center justify-center gap-2 mt-10 pt-6 border-t border-border">
              <button
                onClick={() => goToPage(page - 1)}
                disabled={page <= 1}
                className="p-2 rounded-lg text-muted hover:text-ink hover:bg-paper-warm
                         disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              >
                <ChevronLeft size={18} />
              </button>

              <span className="text-sm font-mono text-muted px-3">
                {page} / {data.total_pages}
              </span>

              <button
                onClick={() => goToPage(page + 1)}
                disabled={page >= data.total_pages}
                className="p-2 rounded-lg text-muted hover:text-ink hover:bg-paper-warm
                         disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              >
                <ChevronRight size={18} />
              </button>
            </div>
          )}
        </>
      )}

      {titlePrompt && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
          <div className="bg-paper border border-border rounded-xl shadow-xl p-6 max-w-sm mx-4 animate-fade-in">
            <h2 className="font-display text-xl text-ink mb-2">Enter post title</h2>
            <p className="text-sm text-muted mb-4">
              This markdown file has no title. Please enter one:
            </p>
            <input
              type="text"
              value={promptTitle}
              onChange={(e) => setPromptTitle(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && promptTitle.trim()) void handleTitleSubmit()
              }}
              placeholder="Post title"
              autoFocus
              className="w-full px-3 py-2 mb-4 bg-paper-warm border border-border rounded-lg
                       text-ink text-sm
                       focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/20"
            />
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setTitlePrompt(null)}
                disabled={uploading}
                className="px-4 py-2 text-sm font-medium text-muted hover:text-ink
                         border border-border rounded-lg transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={() => void handleTitleSubmit()}
                disabled={uploading || !promptTitle.trim()}
                className="px-4 py-2 text-sm font-medium text-white bg-accent hover:bg-accent-light
                         rounded-lg transition-colors disabled:opacity-50"
              >
                {uploading ? 'Uploading...' : 'Upload'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
