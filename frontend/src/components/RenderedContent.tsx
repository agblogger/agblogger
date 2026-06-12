import { useRef } from 'react'
import type { RefObject } from 'react'
import { useRenderedHtml } from '@/hooks/useKatex'
import { useCodeBlockEnhance } from '@/hooks/useCodeBlockEnhance'

interface RenderedContentProps {
  /** Backend-rendered, server-sanitized HTML (e.g. `post.rendered_html`). */
  html: string | null | undefined
  className?: string
  /** External ref onto the content element, e.g. for the table of contents. */
  contentRef?: RefObject<HTMLDivElement | null>
}

/**
 * Renders backend-produced HTML for both posts and pages so they share one
 * presentation pipeline: KaTeX hydration plus code-block language headers and
 * copy buttons. The backend is the single source of rendering and sanitization.
 */
export default function RenderedContent({
  html,
  className = 'prose max-w-none',
  contentRef,
}: RenderedContentProps) {
  const localRef = useRef<HTMLDivElement>(null)
  const ref = contentRef ?? localRef
  const renderedHtml = useRenderedHtml(html)
  useCodeBlockEnhance(ref, renderedHtml)

  return (
    <div
      ref={ref}
      className={className}
      // nosemgrep: typescript.react.security.audit.react-dangerouslysetinnerhtml
      // HTML is rendered and sanitized server-side by the backend rendering pipeline.
      dangerouslySetInnerHTML={{ __html: renderedHtml }}
    />
  )
}
