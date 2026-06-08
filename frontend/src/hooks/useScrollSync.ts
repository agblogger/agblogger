import { type RefObject, useCallback, useEffect, useRef } from 'react'

interface SyncPoint {
  editorPx: number
  previewPx: number
}

interface UseScrollSyncOptions {
  textareaRef: RefObject<HTMLTextAreaElement | null>
  previewRef: RefObject<HTMLDivElement | null>
  content: string
}

interface UseScrollSyncResult {
  syncEditorToPreview: () => void
  syncPreviewToEditor: () => void
}

function setupMirror(mirror: HTMLDivElement, textarea: HTMLTextAreaElement): void {
  const cs = getComputedStyle(textarea)
  mirror.style.fontFamily = cs.fontFamily
  mirror.style.fontSize = cs.fontSize
  mirror.style.lineHeight = cs.lineHeight
  mirror.style.letterSpacing = cs.letterSpacing
  mirror.style.paddingTop = cs.paddingTop
  mirror.style.paddingRight = cs.paddingRight
  mirror.style.paddingBottom = cs.paddingBottom
  mirror.style.paddingLeft = cs.paddingLeft
  mirror.style.whiteSpace = 'pre-wrap'
  mirror.style.wordBreak = cs.wordBreak
  mirror.style.overflowWrap = cs.overflowWrap
  mirror.style.boxSizing = 'border-box'
  // clientWidth excludes the scrollbar so wrapping matches the textarea exactly
  mirror.style.width = `${textarea.clientWidth}px`
}

function buildSyncPoints(
  textarea: HTMLTextAreaElement,
  preview: HTMLDivElement,
  mirror: HTMLDivElement,
  content: string,
): SyncPoint[] {
  setupMirror(mirror, textarea)

  const lines = content.split('\n')
  mirror.innerHTML = ''
  const fragment = document.createDocumentFragment()
  for (const line of lines) {
    const div = document.createElement('div')
    div.style.margin = '0'
    div.style.padding = '0'
    // Zero-width space so empty lines retain their line-height
    div.textContent = line.length > 0 ? line : '​'
    fragment.appendChild(div)
  }
  mirror.appendChild(fragment)

  const editorLines = Array.from(mirror.children).map(
    (child) => (child as HTMLElement).offsetTop,
  )

  const sentinelEls = preview.querySelectorAll<HTMLElement>('[id^="agbpos-L"]')
  return Array.from(sentinelEls)
    .map((el) => {
      const line = parseInt(el.id.slice('agbpos-L'.length), 10)
      const editorPx = editorLines[line] ?? 0
      // Use the next sibling's offsetTop to skip the sentinel's own margin-top,
      // so headings and other block elements with top margin sync to their content start
      const nextEl = el.nextElementSibling as HTMLElement | null
      const previewPx = nextEl?.offsetTop ?? el.offsetTop
      return { editorPx, previewPx }
    })
    .sort((a, b) => a.editorPx - b.editorPx)
}

function editorToPreview(points: SyncPoint[], scrollTop: number): number {
  if (points.length === 0) return 0
  let lo = 0
  let hi = points.length - 1
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if ((points[mid]?.editorPx ?? 0) <= scrollTop) lo = mid
    else hi = mid - 1
  }
  const p0 = points[lo]
  if (!p0) return 0
  const p1 = points[lo + 1]
  if (!p1 || p1.editorPx <= p0.editorPx) return p0.previewPx
  const t = Math.min(1, Math.max(0, (scrollTop - p0.editorPx) / (p1.editorPx - p0.editorPx)))
  return p0.previewPx + t * (p1.previewPx - p0.previewPx)
}

function previewToEditor(points: SyncPoint[], scrollTop: number): number {
  if (points.length === 0) return 0
  let lo = 0
  let hi = points.length - 1
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if ((points[mid]?.previewPx ?? 0) <= scrollTop) lo = mid
    else hi = mid - 1
  }
  const p0 = points[lo]
  if (!p0) return 0
  const p1 = points[lo + 1]
  if (!p1 || p1.previewPx <= p0.previewPx) return p0.editorPx
  const t = Math.min(1, Math.max(0, (scrollTop - p0.previewPx) / (p1.previewPx - p0.previewPx)))
  return p0.editorPx + t * (p1.editorPx - p0.editorPx)
}

export function useScrollSync({
  textareaRef,
  previewRef,
  content,
}: UseScrollSyncOptions): UseScrollSyncResult {
  const pointsRef = useRef<SyncPoint[] | null>(null)
  const mirrorRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    pointsRef.current = null
  }, [content])

  useEffect(() => {
    const mirror = document.createElement('div')
    mirror.style.position = 'absolute'
    mirror.style.top = '-9999px'
    mirror.style.left = '-9999px'
    mirror.style.visibility = 'hidden'
    mirror.style.pointerEvents = 'none'
    document.body.appendChild(mirror)
    mirrorRef.current = mirror
    return () => {
      document.body.removeChild(mirror)
      mirrorRef.current = null
    }
  }, [])

  useEffect(() => {
    const textarea = textareaRef.current
    if (!textarea) return
    const observer = new ResizeObserver(() => {
      pointsRef.current = null
    })
    observer.observe(textarea)
    return () => observer.disconnect()
  }, [textareaRef])

  useEffect(() => {
    const preview = previewRef.current
    if (!preview) return

    const handleLoad = () => {
      pointsRef.current = null
    }

    const attachToImages = () => {
      preview.querySelectorAll('img').forEach((img) => {
        img.removeEventListener('load', handleLoad)
        img.addEventListener('load', handleLoad)
        if (img.complete) handleLoad()
      })
    }

    const mutationObserver = new MutationObserver(() => {
      pointsRef.current = null
      attachToImages()
    })
    mutationObserver.observe(preview, { childList: true, subtree: true })
    attachToImages()

    return () => {
      mutationObserver.disconnect()
      preview.querySelectorAll('img').forEach((img) =>
        img.removeEventListener('load', handleLoad),
      )
    }
  }, [previewRef])

  const getOrBuildPoints = useCallback((): SyncPoint[] | null => {
    if (pointsRef.current) return pointsRef.current
    const textarea = textareaRef.current
    const preview = previewRef.current
    const mirror = mirrorRef.current
    if (!textarea || !preview || !mirror) return null
    const points = buildSyncPoints(textarea, preview, mirror, content)
    pointsRef.current = points
    return points
  }, [textareaRef, previewRef, content])

  const syncEditorToPreview = useCallback(() => {
    const textarea = textareaRef.current
    const preview = previewRef.current
    if (!textarea || !preview) return
    const points = getOrBuildPoints()
    if (!points) return
    preview.scrollTop = editorToPreview(points, textarea.scrollTop)
  }, [textareaRef, previewRef, getOrBuildPoints])

  const syncPreviewToEditor = useCallback(() => {
    const textarea = textareaRef.current
    const preview = previewRef.current
    if (!textarea || !preview) return
    const points = getOrBuildPoints()
    if (!points) return
    textarea.scrollTop = previewToEditor(points, preview.scrollTop)
  }, [textareaRef, previewRef, getOrBuildPoints])

  return { syncEditorToPreview, syncPreviewToEditor }
}
