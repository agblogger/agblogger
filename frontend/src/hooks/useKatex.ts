import { useEffect, useMemo, useState } from 'react'

const MATH_SPAN_RE = /<span class="math (inline|display)">([\s\S]*?)<\/span>/g

const MATH_SPAN_CHECK_RE = /<span class="math (?:inline|display)">/

const HTML_ENTITY_RE = /&(?:amp|lt|gt|quot|#39);/g
const HTML_ENTITY_MAP: Record<string, string> = {
  '&amp;': '&',
  '&lt;': '<',
  '&gt;': '>',
  '&quot;': '"',
  '&#39;': "'",
}

function decodeHtmlEntities(s: string): string {
  return s.replace(HTML_ENTITY_RE, (entity) => HTML_ENTITY_MAP[entity] ?? entity)
}

type KatexRender = (tex: string, opts: { throwOnError: boolean; displayMode: boolean }) => string

let cachedRender: KatexRender | null = null
let katexPromise: Promise<KatexRender> | null = null

function loadKatex(): Promise<KatexRender> {
  if (katexPromise !== null) return katexPromise
  katexPromise = Promise.all([import('katex'), import('katex/dist/katex.min.css')]).then(
    ([mod]) => {
      const render: KatexRender = mod.default.renderToString
      cachedRender = render
      return render
    },
  )
  return katexPromise
}

/**
 * Pre-renders KaTeX math in an HTML string. Replaces Pandoc's
 * `<span class="math inline">` and `<span class="math display">`
 * with KaTeX-rendered HTML so React can manage the final DOM.
 *
 * KaTeX (~200KB) is lazy-loaded on first encounter of math content.
 * Until loaded, the raw HTML is returned unchanged.
 *
 * Used for both full post HTML and rendered excerpts.
 */
export function useRenderedHtml(html: string | null | undefined): string {
  const hasMath = html != null && MATH_SPAN_CHECK_RE.test(html)
  const [render, setRender] = useState<KatexRender | null>(() => cachedRender)

  useEffect(() => {
    if (!hasMath || render !== null) return
    void loadKatex().then((fn) => {
      setRender(() => fn)
    })
  }, [hasMath, render])

  return useMemo(() => {
    if (html == null) return ''
    if (!hasMath || render === null) return html
    return html.replace(MATH_SPAN_RE, (_match, mode: string, tex: string) => {
      const displayMode = mode === 'display'
      const rendered = render(decodeHtmlEntities(tex.trim()), {
        throwOnError: false,
        displayMode,
      })
      return `<span class="math ${mode}">${rendered}</span>`
    })
  }, [html, hasMath, render])
}
