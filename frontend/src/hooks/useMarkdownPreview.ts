import { useEffect, useRef, useState, type RefObject } from 'react'

import api from '@/api/client'
import { useRenderedHtml } from '@/hooks/useKatex'
import { useCodeBlockEnhance } from '@/hooks/useCodeBlockEnhance'

interface UseMarkdownPreviewOptions {
  value: string
  filePath?: string | null
  previewRef: RefObject<HTMLElement | null>
  debounceMs?: number
}

interface UseMarkdownPreviewResult {
  /** KaTeX-hydrated, sanitized HTML ready to mount; empty string when no content. */
  html: string
  /** True when the most recent render request failed. */
  error: boolean
  /** True when the markdown has non-whitespace content. */
  hasContent: boolean
}

/**
 * Owns the editor live-preview pipeline: a debounced `render/preview` call
 * (server renders + sanitizes), KaTeX hydration, and code-block enhancement
 * wired to `previewRef`. Shared by post and page editing so the preview behaves
 * identically everywhere.
 */
export function useMarkdownPreview({
  value,
  filePath,
  previewRef,
  debounceMs = 500,
}: UseMarkdownPreviewOptions): UseMarkdownPreviewResult {
  const [serverHtml, setServerHtml] = useState<string | null>(null)
  const [error, setError] = useState(false)
  const requestRef = useRef(0)
  const hasContent = value.trim().length > 0

  useEffect(() => {
    if (!hasContent) {
      return
    }
    const requestId = ++requestRef.current
    const timer = setTimeout(() => {
      const payload: { markdown: string; file_path?: string } = { markdown: value }
      if (filePath != null) {
        payload.file_path = filePath
      }
      api
        .post('render/preview', { json: payload })
        .json<{ html: string }>()
        .then((resp) => {
          if (requestRef.current === requestId) {
            setServerHtml(resp.html)
            setError(false)
          }
        })
        .catch((err: unknown) => {
          console.error('Preview failed:', err)
          if (requestRef.current === requestId) {
            setError(true)
          }
        })
    }, debounceMs)
    return () => clearTimeout(timer)
  }, [value, filePath, hasContent, debounceMs])

  const html = useRenderedHtml(hasContent ? serverHtml : null)
  useCodeBlockEnhance(previewRef, html)

  return { html, error: hasContent && error, hasContent }
}
