import { useEffect, useRef, useState } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { ArrowLeft, Calendar, User, PenLine, Trash2 } from 'lucide-react'
import { format, parseISO } from 'date-fns'
import { fetchPost, deletePost } from '@/api/posts'
import { useAuthStore } from '@/stores/authStore'
import { HTTPError } from '@/api/client'
import LabelChip from '@/components/labels/LabelChip'
import CrossPostSection from '@/components/crosspost/CrossPostSection'
import ShareButton from '@/components/share/ShareButton'
import ShareBar from '@/components/share/ShareBar'
import { useRenderedHtml } from '@/hooks/useKatex'
import TableOfContents from '@/components/posts/TableOfContents'
import type { PostDetail } from '@/api/client'

export default function PostPage() {
  const { '*': filePath } = useParams()
  const navigate = useNavigate()
  const [post, setPost] = useState<PostDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [deleteMode, setDeleteMode] = useState<'post' | 'all' | null>(null)
  const [deleting, setDeleting] = useState(false)
  const user = useAuthStore((s) => s.user)
  const contentRef = useRef<HTMLDivElement>(null)
  const renderedHtml = useRenderedHtml(post?.rendered_html)

  async function handleDelete(withAssets: boolean) {
    if (filePath === undefined) return
    setDeleting(true)
    setDeleteError(null)
    try {
      await deletePost(filePath, withAssets)
      void navigate('/', { replace: true })
    } catch (err) {
      if (err instanceof HTTPError && err.response.status === 401) {
        setDeleteError('Session expired. Please log in again.')
      } else {
        setDeleteError('Failed to delete post. Please try again.')
      }
      setDeleteMode(null)
    } finally {
      setDeleting(false)
    }
  }

  useEffect(() => {
    if (filePath === undefined) return
    void (async () => {
      setLoading(true)
      setLoadError(null)
      try {
        const p = await fetchPost(filePath)
        setPost(p)
      } catch (err) {
        if (err instanceof HTTPError && err.response.status === 404) {
          setLoadError('Post not found')
        } else {
          setLoadError('Failed to load post. Please try again later.')
        }
      } finally {
        setLoading(false)
      }
    })()
  }, [filePath])

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24" role="status" aria-label="Loading">
        <div className="w-6 h-6 border-2 border-accent/30 border-t-accent rounded-full animate-spin" />
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

  let dateStr = ''
  try {
    const parsed = parseISO(post.created_at.replace(' ', 'T').replace(/\+(\d{2})$/, '+$1:00'))
    dateStr = format(parsed, 'MMMM d, yyyy')
  } catch {
    dateStr = post.created_at.split(' ')[0] ?? ''
  }

  return (
    <article className="animate-fade-in">
      <div className="flex items-center justify-between mb-8">
        <Link
          to="/"
          className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink transition-colors"
        >
          <ArrowLeft size={14} />
          Back to posts
        </Link>
        <TableOfContents contentRef={contentRef} />
      </div>

      <header className="mb-10">
        <h1 className="font-display text-4xl md:text-5xl text-ink leading-tight tracking-tight">
          {post.title}
        </h1>

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

            <ShareButton title={post.title} author={post.author} url={`${window.location.origin}/post/${filePath}`} />
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
                onClick={() => setDeleteMode('post')}
                disabled={deleting}
                className="flex items-center gap-1 text-muted hover:text-red-600 transition-colors disabled:opacity-50"
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
        <div className="mb-6 text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
          {deleteError}
        </div>
      )}

      <div
        ref={contentRef}
        className="prose max-w-none"
        dangerouslySetInnerHTML={{
          __html: renderedHtml,
        }}
      />

      <ShareBar title={post.title} author={post.author} url={`${window.location.origin}/post/${filePath}`} />

      {user?.is_admin === true && filePath !== undefined && filePath !== '' && (
        <CrossPostSection filePath={filePath} post={post} />
      )}

      <footer className="mt-16 pt-8 border-t border-border">
        <Link
          to="/"
          className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink transition-colors"
        >
          <ArrowLeft size={14} />
          Back to posts
        </Link>
      </footer>

      {deleteMode && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
          <div className="bg-paper border border-border rounded-xl shadow-xl p-6 max-w-sm mx-4 animate-fade-in">
            <h2 className="font-display text-xl text-ink mb-2">Delete post?</h2>
            {post.file_path.endsWith('/index.md') ? (
              <>
                <p className="text-sm text-muted mb-6">
                  This post has a directory that may contain uploaded files.
                </p>
                <div className="flex flex-col gap-2 mb-4">
                  <button
                    onClick={() => void handleDelete(false)}
                    disabled={deleting}
                    className="w-full px-4 py-2 text-sm font-medium text-ink
                             border border-border rounded-lg hover:bg-paper-warm
                             transition-colors disabled:opacity-50 text-left"
                  >
                    Delete post only
                    <span className="block text-xs text-muted font-normal mt-0.5">
                      Removes the markdown file, keeps uploaded files
                    </span>
                  </button>
                  <button
                    onClick={() => void handleDelete(true)}
                    disabled={deleting}
                    className="w-full px-4 py-2 text-sm font-medium text-red-600
                             border border-red-200 rounded-lg hover:bg-red-50
                             transition-colors disabled:opacity-50 text-left"
                  >
                    Delete with all files
                    <span className="block text-xs text-red-400 font-normal mt-0.5">
                      Removes the post and all uploaded assets
                    </span>
                  </button>
                </div>
              </>
            ) : (
              <p className="text-sm text-muted mb-6">
                This will permanently delete &ldquo;{post.title}&rdquo;. This cannot be undone.
              </p>
            )}
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setDeleteMode(null)}
                disabled={deleting}
                className="px-4 py-2 text-sm font-medium text-muted hover:text-ink
                         border border-border rounded-lg transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
              {!post.file_path.endsWith('/index.md') && (
                <button
                  onClick={() => void handleDelete(false)}
                  disabled={deleting}
                  data-testid="confirm-delete"
                  className="px-4 py-2 text-sm font-medium text-white bg-red-600 hover:bg-red-700
                           rounded-lg transition-colors disabled:opacity-50"
                >
                  {deleting ? 'Deleting...' : 'Delete'}
                </button>
              )}
            </div>
            {deleting && (
              <p className="text-xs text-muted mt-3 text-center">Deleting...</p>
            )}
          </div>
        </div>
      )}
    </article>
  )
}
