import { type RefObject, useCallback, useEffect, useRef, useState } from 'react'

interface SentinelEntry {
  line: number
  top: number
}

interface SyncMap {
  editorLines: number[]
  sentinels: SentinelEntry[]
}

interface UseScrollSyncOptions {
  textareaRef: RefObject<HTMLTextAreaElement | null>
  previewRef: RefObject<HTMLDivElement | null>
  content: string
}

interface UseScrollSyncResult {
  syncEnabled: boolean
  toggleSync: () => void
  onEditorScroll: () => void
  onPreviewScroll: () => void
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

function buildSyncMap(
  textarea: HTMLTextAreaElement,
  preview: HTMLDivElement,
  mirror: HTMLDivElement,
  content: string,
): SyncMap {
  setupMirror(mirror, textarea)

  // Populate mirror with one div per source line
  const lines = content.split('\n')
  mirror.innerHTML = ''
  const fragment = document.createDocumentFragment()
  for (const line of lines) {
    const div = document.createElement('div')
    div.style.margin = '0'
    div.style.padding = '0'
    // Use a zero-width space so empty lines retain their line-height
    div.textContent = line.length > 0 ? line : '​'
    fragment.appendChild(div)
  }
  mirror.appendChild(fragment)

  const editorLines = Array.from(mirror.children).map(
    (child) => (child as HTMLElement).offsetTop,
  )

  const sentinelEls = preview.querySelectorAll<HTMLElement>('[id^="agbpos-L"]')
  const sentinels: SentinelEntry[] = Array.from(sentinelEls)
    .map((el) => ({
      line: parseInt(el.id.slice('agbpos-L'.length), 10),
      top: el.offsetTop,
    }))
    .sort((a, b) => a.line - b.line)

  return { editorLines, sentinels }
}

// Returns fractional line index for a given editor scrollTop
function editorScrollToLine(editorLines: number[], scrollTop: number): number {
  if (editorLines.length === 0) return 0
  let lo = 0
  let hi = editorLines.length - 1
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if (editorLines[mid] <= scrollTop) lo = mid
    else hi = mid - 1
  }
  const lineTop = editorLines[lo]
  const nextTop = editorLines[lo + 1]
  if (nextTop === undefined || nextTop <= lineTop) return lo
  return lo + Math.min(1, (scrollTop - lineTop) / (nextTop - lineTop))
}

// Returns preview scrollTop for a fractional line index
function lineToPreviewScroll(sentinels: SentinelEntry[], fractionalLine: number): number {
  if (sentinels.length === 0) return 0
  let lo = 0
  let hi = sentinels.length - 1
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if (sentinels[mid].line <= fractionalLine) lo = mid
    else hi = mid - 1
  }
  const s0 = sentinels[lo]
  const s1 = sentinels[lo + 1]
  if (!s1 || s1.line <= s0.line) return s0.top
  const t = Math.min(1, Math.max(0, (fractionalLine - s0.line) / (s1.line - s0.line)))
  return s0.top + t * (s1.top - s0.top)
}

// Returns fractional line index for a given preview scrollTop
function previewScrollToLine(sentinels: SentinelEntry[], scrollTop: number): number {
  if (sentinels.length === 0) return 0
  let lo = 0
  let hi = sentinels.length - 1
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if (sentinels[mid].top <= scrollTop) lo = mid
    else hi = mid - 1
  }
  const s0 = sentinels[lo]
  const s1 = sentinels[lo + 1]
  if (!s1 || s1.top <= s0.top) return s0.line
  const t = Math.min(1, Math.max(0, (scrollTop - s0.top) / (s1.top - s0.top)))
  return s0.line + t * (s1.line - s0.line)
}

// Returns editor scrollTop for a fractional line index
function lineToEditorScroll(editorLines: number[], fractionalLine: number): number {
  if (editorLines.length === 0) return 0
  const idx = Math.min(Math.floor(fractionalLine), editorLines.length - 1)
  const fraction = fractionalLine - Math.floor(fractionalLine)
  const lineTop = editorLines[idx] ?? 0
  const nextTop = editorLines[idx + 1]
  if (nextTop === undefined) return lineTop
  return lineTop + fraction * (nextTop - lineTop)
}

export function useScrollSync({
  textareaRef,
  previewRef,
  content,
}: UseScrollSyncOptions): UseScrollSyncResult {
  const [syncEnabled, setSyncEnabled] = useState(true)
  const syncEnabledRef = useRef(syncEnabled)
  const mapRef = useRef<SyncMap | null>(null)
  const syncingRef = useRef(false)
  const mirrorRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    syncEnabledRef.current = syncEnabled
  }, [syncEnabled])

  // Invalidate map when content changes
  useEffect(() => {
    mapRef.current = null
  }, [content])

  // Create mirror div on mount
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

  const getOrBuildMap = useCallback((): SyncMap | null => {
    if (mapRef.current) return mapRef.current
    const textarea = textareaRef.current
    const preview = previewRef.current
    const mirror = mirrorRef.current
    if (!textarea || !preview || !mirror) return null
    const map = buildSyncMap(textarea, preview, mirror, content)
    mapRef.current = map
    return map
  }, [textareaRef, previewRef, content])

  const toggleSync = useCallback(() => setSyncEnabled((s) => !s), [])

  const onEditorScroll = useCallback(() => {
    if (!syncEnabledRef.current || syncingRef.current) return
    const textarea = textareaRef.current
    const preview = previewRef.current
    if (!textarea || !preview) return
    const map = getOrBuildMap()
    if (!map) return
    const fractionalLine = editorScrollToLine(map.editorLines, textarea.scrollTop)
    const previewTop = lineToPreviewScroll(map.sentinels, fractionalLine)
    syncingRef.current = true
    preview.scrollTop = previewTop
    requestAnimationFrame(() => {
      syncingRef.current = false
    })
  }, [textareaRef, previewRef, getOrBuildMap])

  const onPreviewScroll = useCallback(() => {
    if (!syncEnabledRef.current || syncingRef.current) return
    const textarea = textareaRef.current
    const preview = previewRef.current
    if (!textarea || !preview) return
    const map = getOrBuildMap()
    if (!map) return
    const fractionalLine = previewScrollToLine(map.sentinels, preview.scrollTop)
    const editorTop = lineToEditorScroll(map.editorLines, fractionalLine)
    syncingRef.current = true
    textarea.scrollTop = editorTop
    requestAnimationFrame(() => {
      syncingRef.current = false
    })
  }, [textareaRef, previewRef, getOrBuildMap])

  return { syncEnabled, toggleSync, onEditorScroll, onPreviewScroll }
}
