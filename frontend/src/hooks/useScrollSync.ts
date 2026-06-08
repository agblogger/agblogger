import { useCallback, useEffect, useRef, useState } from 'react'

interface SentinelEntry {
  line: number
  top: number
}

interface SyncMap {
  editorLines: number[]
  sentinels: SentinelEntry[]
}

interface UseScrollSyncOptions {
  textareaRef: React.RefObject<HTMLTextAreaElement>
  previewRef: React.RefObject<HTMLDivElement>
  content: string
}

interface UseScrollSyncResult {
  syncEnabled: boolean
  toggleSync: () => void
  onEditorScroll: () => void
  onPreviewScroll: () => void
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

  // Keep syncEnabledRef in sync with state
  useEffect(() => {
    syncEnabledRef.current = syncEnabled
  }, [syncEnabled])

  // Invalidate map on content change
  useEffect(() => {
    mapRef.current = null
  }, [content])

  // Create mirror div on mount, remove on unmount
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

  const toggleSync = useCallback(() => setSyncEnabled((s) => !s), [])

  const onEditorScroll = useCallback(() => {
    if (!syncEnabledRef.current || syncingRef.current) return
    const textarea = textareaRef.current
    const preview = previewRef.current
    if (!textarea || !preview) return
    // Map building and sync handled in Task 6
  }, [textareaRef, previewRef])

  const onPreviewScroll = useCallback(() => {
    if (!syncEnabledRef.current || syncingRef.current) return
    const textarea = textareaRef.current
    const preview = previewRef.current
    if (!textarea || !preview) return
    // Map building and sync handled in Task 6
  }, [textareaRef, previewRef])

  return { syncEnabled, toggleSync, onEditorScroll, onPreviewScroll }
}
