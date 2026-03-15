import { useEffect, useState } from 'react'
import LoadingSpinner from '@/components/LoadingSpinner'
import { useParams, Link } from 'react-router-dom'
import { Tag, Settings } from 'lucide-react'

import BackLink from '@/components/BackLink'
import ErrorBlock from '@/components/ErrorBlock'
import LabelChip from '@/components/labels/LabelChip'
import ParentLabelLinks from '@/components/labels/ParentLabelLinks'
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
    return <LoadingSpinner />
  }

  if (error !== null) {
    return <ErrorBlock message={error} backTo="/labels" backLabel="Back to labels" />
  }

  const hasHierarchy =
    label !== null && (label.children.length > 0 || label.parents.length > 0)

  return (
    <div className="animate-fade-in">
      <div className="mb-6">
        <BackLink to="/labels" label="All labels" />
      </div>

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
        <p className={`text-muted${hasHierarchy ? '' : ' mb-8'}`}>{label.names.join(', ')}</p>
      )}

      {label !== null && label.children.length > 0 && (
        <div className={`mt-4${label.parents.length > 0 ? '' : ' mb-8'}`}>
          <h2 className="text-sm font-medium text-muted mb-2">Children</h2>
          <div className="flex flex-wrap gap-2">
            {label.children.map((c) => (
              <LabelChip key={c} labelId={c} />
            ))}
          </div>
        </div>
      )}

      {label !== null && label.parents.length > 0 && (
        <div className={`${label.children.length > 0 ? 'mt-3' : 'mt-4'} mb-8`}>
          <h2 className="text-sm font-medium text-muted mb-2">Parents</h2>
          <div className="text-sm">
            <ParentLabelLinks parents={label.parents} />
          </div>
        </div>
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
