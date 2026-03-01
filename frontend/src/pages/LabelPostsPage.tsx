import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { ArrowLeft, Tag, Settings } from 'lucide-react'

import PostCard from '@/components/posts/PostCard'
import { useAuthStore } from '@/stores/authStore'
import { fetchLabelPosts, fetchLabel } from '@/api/labels'
import { HTTPError } from '@/api/client'
import type { LabelResponse, PostListResponse } from '@/api/client'

export default function LabelPostsPage() {
  const { labelId } = useParams()
  const user = useAuthStore((s) => s.user)
  const [label, setLabel] = useState<LabelResponse | null>(null)
  const [data, setData] = useState<PostListResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (labelId === undefined) return
    void (async () => {
      setLoading(true)
      setError(null)
      try {
        const [l, d] = await Promise.all([fetchLabel(labelId), fetchLabelPosts(labelId)])
        setLabel(l)
        setData(d)
      } catch (err) {
        if (err instanceof HTTPError && err.response.status === 404) {
          setError('Label not found.')
        } else if (err instanceof HTTPError && err.response.status === 401) {
          setError('Session expired. Please log in again.')
        } else {
          setError('Failed to load label posts. Please try again later.')
        }
      } finally {
        setLoading(false)
      }
    })()
  }, [labelId])

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24" role="status" aria-label="Loading">
        <div className="w-6 h-6 border-2 border-accent/30 border-t-accent rounded-full animate-spin" />
      </div>
    )
  }

  if (error !== null) {
    return (
      <div className="text-center py-24">
        <p className="text-red-600">{error}</p>
        <Link to="/labels" className="text-accent text-sm hover:underline mt-4 inline-block">
          Back to labels
        </Link>
      </div>
    )
  }

  return (
    <div className="animate-fade-in">
      <Link
        to="/labels"
        className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink transition-colors mb-6"
      >
        <ArrowLeft size={14} />
        All labels
      </Link>

      <div className="flex items-center gap-3 mb-2">
        <Tag size={20} className="text-accent" />
        <h1 className="font-display text-3xl text-ink">#{labelId}</h1>
        {user && (
          <Link
            to={`/labels/${labelId}/settings`}
            className="ml-auto p-1.5 text-muted hover:text-ink transition-colors rounded-lg
                     hover:bg-paper-warm"
            aria-label="Label settings"
          >
            <Settings size={18} />
          </Link>
        )}
      </div>

      {label !== null && label.names.length > 0 && (
        <p className="text-muted mb-8">{label.names.join(', ')}</p>
      )}

      {!data || data.posts.length === 0 ? (
        <p className="text-muted text-center py-16">No posts with this label.</p>
      ) : (
        <div className="divide-y divide-border/60">
          {data.posts.map((post, i) => (
            <PostCard key={post.id} post={post} index={i} />
          ))}
        </div>
      )}
    </div>
  )
}
