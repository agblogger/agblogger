import { memo } from 'react'
import { Link } from 'react-router-dom'
import type { PostSummary } from '@/api/client'
import LabelChip from '@/components/labels/LabelChip'
import { useRenderedHtml } from '@/hooks/useKatex'
import { formatRelativeDate } from '@/utils/date'
import { postUrl } from '@/utils/postUrl'

interface PostCardProps {
  post: PostSummary
  index?: number
}

function PostCardInner({ post, index = 0 }: PostCardProps) {
  const postHref = postUrl(post.file_path)
  const staggerClass = `stagger-${Math.min(index + 1, 8)}`
  const sanitizedExcerpt = useRenderedHtml(post.rendered_excerpt)

  const dateStr = formatRelativeDate(post.created_at)

  return (
    <article
      className={`group relative opacity-0 animate-slide-up ${staggerClass} py-6 -mx-4 px-4 rounded-xl border-l-2 border-l-transparent transition-all duration-200 hover:bg-paper-warm/60 hover:shadow-lg hover:border-l-accent hover:z-10`}
    >
      <Link to={postHref} className="absolute inset-0" aria-label={post.title} />
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline gap-2 flex-wrap">
            <h2 className="font-display text-xl text-ink group-hover:text-accent transition-colors leading-snug">
              {post.title}
            </h2>
            {post.is_draft && (
              <span className="text-[10px] font-mono font-semibold uppercase tracking-widest px-1.5 py-0.5 bg-muted/10 text-muted border border-muted/30 rounded shrink-0">
                DRAFT
              </span>
            )}
          </div>

          {post.subtitle != null && (
            <p data-testid="card-subtitle" className="text-base text-ink/60 mt-1 leading-snug">
              {post.subtitle}
            </p>
          )}

          {sanitizedExcerpt !== '' && (
            <div
              className="mt-2 text-sm text-muted leading-relaxed line-clamp-2 prose-excerpt"
              // Excerpt HTML is rendered and sanitized server-side.
              // nosemgrep: typescript.react.security.audit.react-dangerouslysetinnerhtml.react-dangerouslysetinnerhtml, typescript.react.react-dangerouslysetinnerhtml-prop.react-dangerouslysetinnerhtml-prop
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
                <div className="relative z-10 flex gap-1.5 flex-wrap">
                  {post.labels.map((label) => (
                    <LabelChip key={label} labelId={label} />
                  ))}
                </div>
              </>
            )}
          </div>
        </div>

        <div className="hidden sm:block w-1 h-12 rounded-full bg-border group-hover:bg-accent transition-colors shrink-0 mt-1" />
      </div>
    </article>
  )
}

const PostCard = memo(PostCardInner)
export default PostCard
