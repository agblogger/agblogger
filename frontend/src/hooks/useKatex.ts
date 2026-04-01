import DOMPurify from 'dompurify'
import { useEffect, useMemo, useState } from 'react'

const MATH_SPAN_RE = /<span class="math (inline|display)">([\s\S]*?)<\/span>/g
const MATH_SPAN_CHECK_RE = /<span class="math (?:inline|display)">/
const YOUTUBE_IFRAME_SRC_RE =
  /^https:\/\/www\.(?:youtube\.com\/(?:embed|shorts)\/|youtube-nocookie\.com\/embed\/)[a-zA-Z0-9_-]{11}(?:\?[a-zA-Z0-9_=&%-]*)?$/
const YOUTUBE_IFRAME_SANDBOX =
  'allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox'
const YOUTUBE_IFRAME_REFERRER_POLICY = 'origin'
const YOUTUBE_IFRAME_LOADING = 'lazy'
const IFRAME_TOKEN_PREFIX = `__AGBLOGGER_YOUTUBE_IFRAME_${Date.now().toString(36)}_`
const ALLOWED_IFRAME_ATTRS = new Set([
  'allowfullscreen',
  'loading',
  'referrerpolicy',
  'sandbox',
  'src',
])

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

let iframeTokenCounter = 0

function randomToken(): string {
  iframeTokenCounter += 1
  return `${IFRAME_TOKEN_PREFIX}${iframeTokenCounter}__`
}

function canonicalizeApprovedIframe(iframe: HTMLIFrameElement): string {
  const src = iframe.getAttribute('src')
  if (src === null) return ''
  return (
    `<iframe src="${src}"` +
    ` sandbox="${YOUTUBE_IFRAME_SANDBOX}"` +
    ' allowfullscreen="allowfullscreen"' +
    ` referrerpolicy="${YOUTUBE_IFRAME_REFERRER_POLICY}"` +
    ` loading="${YOUTUBE_IFRAME_LOADING}"></iframe>`
  )
}

function isApprovedYouTubeIframe(iframe: HTMLIFrameElement): boolean {
  const src = iframe.getAttribute('src')?.trim() ?? ''
  if (!YOUTUBE_IFRAME_SRC_RE.test(src)) return false
  if (iframe.getAttribute('sandbox') !== YOUTUBE_IFRAME_SANDBOX) return false
  if (!iframe.hasAttribute('allowfullscreen')) return false
  if (iframe.getAttribute('referrerpolicy') !== YOUTUBE_IFRAME_REFERRER_POLICY) return false
  if (iframe.getAttribute('loading') !== YOUTUBE_IFRAME_LOADING) return false

  const attrNames = iframe.getAttributeNames()
  if (attrNames.length !== ALLOWED_IFRAME_ATTRS.size) return false
  return attrNames.every((name) => ALLOWED_IFRAME_ATTRS.has(name.toLowerCase()))
}

function sanitizeRenderedContent(html: string): string {
  if (!html.includes('<iframe') || typeof document === 'undefined') {
    return DOMPurify.sanitize(html)
  }

  const template = document.createElement('template')
  template.innerHTML = html

  const preservedIframes = new Map<string, string>()
  for (const iframe of Array.from(template.content.querySelectorAll('iframe'))) {
    if (!isApprovedYouTubeIframe(iframe)) continue

    const token = randomToken()
    preservedIframes.set(token, canonicalizeApprovedIframe(iframe))
    iframe.replaceWith(document.createTextNode(token))
  }

  const sanitized = DOMPurify.sanitize(template.innerHTML)
  let restored = sanitized
  for (const [token, iframeHtml] of preservedIframes) {
    restored = restored.replace(token, iframeHtml)
  }
  return restored
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
 * All output is sanitized with DOMPurify as defense-in-depth —
 * the backend already sanitizes rendered HTML, but KaTeX inserts
 * client-generated markup that bypasses that pipeline.
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
    if (!hasMath || render === null) return sanitizeRenderedContent(html)
    const rendered = html.replace(MATH_SPAN_RE, (_match, mode: string, tex: string) => {
      const displayMode = mode === 'display'
      const katexHtml = render(decodeHtmlEntities(tex.trim()), {
        throwOnError: false,
        displayMode,
      })
      return `<span class="math ${mode}">${katexHtml}</span>`
    })
    return sanitizeRenderedContent(rendered)
  }, [html, hasMath, render])
}
