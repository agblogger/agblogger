import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { Calendar, User, PenLine, Trash2 } from 'lucide-react'
import { fetchPost, deletePost, fetchPostForEdit, updatePost } from '@/api/posts'
import AlertBanner from '@/components/AlertBanner'
import BackLink from '@/components/BackLink'
import { useAuthStore } from '@/stores/authStore'
import { HTTPError } from '@/api/client'
import { parseErrorDetail } from '@/api/parseError'
import LabelChip from '@/components/labels/LabelChip'
import CrossPostSection from '@/components/crosspost/CrossPostSection'
import ShareButton from '@/components/share/ShareButton'
import ShareBar from '@/components/share/ShareBar'
import { useRenderedHtml } from '@/hooks/useKatex'
import { useCodeBlockEnhance } from '@/hooks/useCodeBlockEnhance'
import TableOfContents from '@/components/posts/TableOfContents'
import type { PostDetail } from '@/api/client'
import { formatDate } from '@/utils/date'
export default function PostPage() {
  const { '*': slug } = useParams()
  const navigate = useNavigate()
  const [post, setPost] = useState<PostDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [publishError, setPublishError] = useState<string | null>(null)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [publishing, setPublishing] = useState(false)
  const user = useAuthStore((s) => s.user)
  const contentRef = useRef<HTMLDivElement>(null)
  const renderedHtml = useRenderedHtml(post?.rendered_html)
  useCodeBlockEnhance(contentRef, renderedHtml)

  async function handleDelete() {
    if (!post) return
    setDeleting(true)
    setDeleteError(null)
    try {
      await deletePost(post.file_path, true)
      void navigate('/', { replace: true })
    } catch (err) {
      if (err instanceof HTTPError && err.response.status === 401) {
        setDeleteError('Session expired. Please log in again.')
      } else {
        setDeleteError('Failed to delete post. Please try again.')
      }
      setShowDeleteConfirm(false)
    } finally {
      setDeleting(false)
    }
  }

  async function handlePublish() {
    if (!post) return
    setPublishing(true)
    setPublishError(null)
    try {
      const editData = await fetchPostForEdit(post.file_path)
      const updated = await updatePost(post.file_path, {
        title: editData.title,
        body: editData.body,
        labels: editData.labels,
        is_draft: false,
      })
      setPost(updated)
    } catch (err) {
      if (err instanceof HTTPError && err.response.status === 401) {
        setPublishError('Session expired. Please log in again.')
      } else if (err instanceof HTTPError && err.response.status < 500) {
        const detail = await parseErrorDetail(
          err.response,
          'Failed to publish post. Please try again.',
        )
        setPublishError(detail)
      } else {
        setPublishError('Failed to publish post. Please try again.')
      }
    } finally {
      setPublishing(false)
    }
  }

  useEffect(() => {
    if (slug === undefined || slug === '') return
    void (async () => {
      setLoading(true)
      setLoadError(null)
      try {
        const p = await fetchPost(slug)
        setPost(p)
      } catch (err) {
        if (err instanceof HTTPError && err.response.status === 404) {
          setLoadError('Post not found')
        } else if (err instanceof HTTPError && err.response.status === 401) {
          setLoadError('Session expired. Please log in again.')
        } else {
          setLoadError('Failed to load post. Please try again later.')
        }
      } finally {
        setLoading(false)
      }
    })()
  }, [slug])

  if (loading) {
    return (
      <div className="animate-fade-in" role="status" aria-label="Loading post">
        <div className="flex items-center justify-between mb-8">
          <div className="h-4 bg-border/40 rounded w-24 animate-pulse" />
        </div>
        <div className="mb-10 space-y-4">
          <div className="h-10 bg-border/50 rounded w-4/5 animate-pulse" />
          <div className="flex items-center gap-4">
            <div className="h-3.5 bg-border/30 rounded w-28 animate-pulse" />
            <div className="h-3.5 bg-border/30 rounded w-20 animate-pulse" />
          </div>
          <div className="h-px bg-border/40" />
        </div>
        <div className="space-y-4">
          <div className="h-4 bg-border/40 rounded w-full animate-pulse" />
          <div className="h-4 bg-border/40 rounded w-full animate-pulse" />
          <div className="h-4 bg-border/40 rounded w-3/4 animate-pulse" />
          <div className="h-4 bg-border/40 rounded w-full animate-pulse" />
          <div className="h-4 bg-border/40 rounded w-5/6 animate-pulse" />
          <div className="h-4 bg-border/40 rounded w-2/3 animate-pulse" />
        </div>
      </div>
    )
  }

  if (loadError !== null || post === null) {
    return (
      <div className="text-center py-24">
        <p className="font-display text-3xl text-muted italic">
          {loadError === 'Post not found' ? '404' : 'Error'}
        </p>
        <p className="text-sm text-muted mt-2">{loadError ?? 'Post not found'}</p>
        <Link to="/" className="text-accent text-sm hover:underline mt-4 inline-block">
          Back to timeline
        </Link>
      </div>
    )
  }

  const dateStr = formatDate(post.created_at, 'MMMM d, yyyy')

  return (
    <article className="animate-fade-in xl:flex xl:gap-8">
      <div className="flex-1 min-w-0">
      <div className="flex items-center justify-between mb-8">
        <BackLink to="/" label="Back to posts" />
        <div className="xl:hidden">
          <TableOfContents contentRef={contentRef} />
        </div>
      </div>

      <header className="mb-10">
        <h1 className="font-display text-4xl md:text-5xl text-ink leading-tight tracking-tight">
          {post.title}
        </h1>

        {user && post.is_draft && (
          <div className="flex items-center justify-between mt-3">
            <span className="text-xs px-2 py-0.5 bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 rounded-full font-medium">
              Draft
            </span>
            <button
              onClick={() => void handlePublish()}
              disabled={publishing}
              className="px-4 py-2 text-sm font-medium text-white bg-accent hover:bg-accent/90 rounded-lg transition-colors disabled:opacity-50"
            >
              {publishing ? 'Publishing...' : 'Publish'}
            </button>
          </div>
        )}

        {publishError !== null && (
          <AlertBanner variant="error" className="mt-3">{publishError}</AlertBanner>
        )}

        <div className="mt-5 text-sm text-muted">
          <div className="flex items-center gap-4 flex-wrap">
            <div className="flex items-center gap-1.5">
              <Calendar size={14} />
              <time>{dateStr}</time>
            </div>

            {post.author !== null && (
              <div className="flex items-center gap-1.5">
                <User size={14} />
                <span>{post.author}</span>
              </div>
            )}

            {post.labels.length > 0 && (
              <div className="flex gap-1.5 flex-wrap">
                {post.labels.map((label) => (
                  <LabelChip key={label} labelId={label} />
                ))}
              </div>
            )}

            <ShareButton
              title={post.title}
              author={post.author}
              url={`${window.location.origin}/post/${slug}`}
              disabled={post.is_draft}
            />
          </div>

          {user && (
            <div className="flex items-center gap-3 mt-3">
              <Link
                to={`/editor/${post.file_path}`}
                className="flex items-center gap-1 text-accent hover:underline"
              >
                <PenLine size={14} />
                Edit
              </Link>
              <button
                onClick={() => setShowDeleteConfirm(true)}
                disabled={deleting}
                className="flex items-center gap-1 text-muted hover:text-red-600 dark:hover:text-red-400 transition-colors disabled:opacity-50"
              >
                <Trash2 size={14} />
                Delete
              </button>
            </div>
          )}
        </div>

        <div className="mt-6 h-px bg-gradient-to-r from-accent/40 via-border to-transparent" />
      </header>

      {deleteError !== null && (
        <AlertBanner variant="error" className="mb-6">{deleteError}</AlertBanner>
      )}

      <div
        ref={contentRef}
        className="prose max-w-none"
        // nosemgrep: typescript.react.security.audit.react-dangerouslysetinnerhtml
        // HTML is rendered and sanitized server-side by the backend rendering pipeline.
        dangerouslySetInnerHTML={{
          __html: renderedHtml,
        }}
      />

      <ShareBar
        title={post.title}
        author={post.author}
        url={`${window.location.origin}/post/${slug}`}
        disabled={post.is_draft}
      />

      {user?.is_admin === true && post.file_path !== '' && (
        <CrossPostSection filePath={post.file_path} post={post} />
      )}

      <footer className="mt-16 pt-8 border-t border-border">
        <BackLink to="/" label="Back to posts" />
      </footer>
      </div>

      <aside className="hidden xl:block xl:w-56 xl:shrink-0">
        <TableOfContents contentRef={contentRef} variant="sidebar" />
      </aside>

      {showDeleteConfirm &&
        createPortal(
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
            <div className="bg-paper border border-border rounded-xl shadow-xl p-6 max-w-sm mx-4 animate-fade-in">
              <h2 className="font-display text-xl text-ink mb-2">Delete post?</h2>
              <p className="text-sm text-muted mb-6">
                This will permanently delete &ldquo;{post.title}&rdquo;. This cannot be undone.
              </p>
              <div className="flex justify-end gap-3">
                <button
                  onClick={() => setShowDeleteConfirm(false)}
                  disabled={deleting}
                  className="px-4 py-2 text-sm font-medium text-muted hover:text-ink
                           border border-border rounded-lg transition-colors disabled:opacity-50"
                >
                  Cancel
                </button>
                <button
                  onClick={() => void handleDelete()}
                  disabled={deleting}
                  data-testid="confirm-delete"
                  className="px-4 py-2 text-sm font-medium text-white bg-red-600 hover:bg-red-700
                           rounded-lg transition-colors disabled:opacity-50"
                >
                  {deleting ? 'Deleting...' : 'Delete'}
                </button>
              </div>
            </div>
          </div>,
          document.body,
        )}
    </article>
  )
}
