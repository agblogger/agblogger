import DOMPurify from 'dompurify'
import { Link } from 'react-router-dom'
import type { PostSummary } from '@/api/client'
import LabelChip from '@/components/labels/LabelChip'
import { useRenderedHtml } from '@/hooks/useKatex'
import { formatRelativeDate } from '@/utils/date'

interface PostCardProps {
  post: PostSummary
  index?: number
}

export default function PostCard({ post, index = 0 }: PostCardProps) {
  const postUrl = `/post/${post.file_path}`
  const staggerClass = `stagger-${Math.min(index + 1, 8)}`
  const rawExcerpt = useRenderedHtml(post.rendered_excerpt)
  const sanitizedExcerpt = rawExcerpt !== '' ? DOMPurify.sanitize(rawExcerpt) : ''

  const dateStr = formatRelativeDate(post.created_at)

  return (
    <article
      className={`group opacity-0 animate-slide-up ${staggerClass}`}
    >
      <Link to={postUrl} className="block py-6 -mx-4 px-4 rounded-xl border-l-2 border-l-transparent transition-all duration-200 hover:bg-paper-warm/60 hover:-translate-y-1 hover:shadow-lg hover:scale-[1.005] hover:border-l-accent">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            <h2 className="font-display text-xl text-ink group-hover:text-accent transition-colors leading-snug">
              {post.title}
            </h2>

            {sanitizedExcerpt !== '' && (
              <div
                className="mt-2 text-sm text-muted leading-relaxed line-clamp-2 prose-excerpt"
                dangerouslySetInnerHTML={{ __html: sanitizedExcerpt }}
              />
            )}

            <div className="mt-3 flex items-center gap-3 flex-wrap">
              <span className="text-xs text-muted font-mono tracking-wide uppercase">
                {dateStr}
              </span>

              {post.author !== null && (
                <>
                  <span className="text-border-dark">·</span>
                  <span className="text-xs text-muted">{post.author}</span>
                </>
              )}

              {post.labels.length > 0 && (
                <>
                  <span className="text-border-dark">·</span>
                  <div className="flex gap-1.5 flex-wrap">
                    {post.labels.map((label) => (
                      <LabelChip key={label} labelId={label} clickable={false} />
                    ))}
                  </div>
                </>
              )}

              {post.is_draft && (
                <span className="text-xs px-2 py-0.5 bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 rounded-full font-medium">
                  Draft
                </span>
              )}
            </div>
          </div>

          <div className="hidden sm:block w-1 h-12 rounded-full bg-border group-hover:bg-accent transition-colors shrink-0 mt-1" />
        </div>
      </Link>
    </article>
  )
}
