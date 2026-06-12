import { useRef } from 'react'
import type { RefObject } from 'react'
import { useRenderedHtml } from '@/hooks/useKatex'
import { useCodeBlockEnhance } from '@/hooks/useCodeBlockEnhance'

const FIRST_H1 = /<h1[^>]*>[\s\S]*?<\/h1>\s*/i

interface RenderedContentProps {
  /** Backend-rendered, server-sanitized HTML (e.g. `post.rendered_html`). */
  html: string | null | undefined
  /** Strip the leading `<h1>` from the body (pages render their title separately). */
  stripFirstH1?: boolean
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
  stripFirstH1 = false,
  className = 'prose max-w-none',
  contentRef,
}: RenderedContentProps) {
  const localRef = useRef<HTMLDivElement>(null)
  const ref = contentRef ?? localRef
  const renderedHtml = useRenderedHtml(html)
  const finalHtml = stripFirstH1 ? renderedHtml.replace(FIRST_H1, '') : renderedHtml
  useCodeBlockEnhance(ref, finalHtml)

  return (
    <div
      ref={ref}
      className={className}
      // nosemgrep: typescript.react.security.audit.react-dangerouslysetinnerhtml
      // HTML is rendered and sanitized server-side by the backend rendering pipeline.
      dangerouslySetInnerHTML={{ __html: finalHtml }}
    />
  )
}
