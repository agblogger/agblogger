import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useBlocker } from 'react-router-dom'

const AUTO_SAVE_DEBOUNCE_MS = 3000

/** Bump when the persisted draft shape changes so stale drafts are ignored. */
export const DRAFT_SCHEMA_VERSION = 2

export function buildEditorDraftStorageKey(userId: number, filePath?: string): string {
  return `agblogger:draft:user:${userId}:${filePath ?? 'new'}`
}

export interface DraftData {
  title: string
  subtitle: string
  body: string
  labels: string[]
  isDraft: boolean
  savedAt?: string
  _v?: number
}

interface UseEditorAutoSaveParams {
  key: string
  currentState: DraftData
  onRestore: (draft: DraftData) => void
  enabled?: boolean
}

interface UseEditorAutoSaveReturn {
  isDirty: boolean
  draftAvailable: boolean
  draftSavedAt: string | null
  restoreDraft: () => void
  discardDraft: () => void
  markSaved: () => void
}

function statesEqual(a: DraftData, b: DraftData): boolean {
  if (a.title !== b.title) return false
  if (a.subtitle !== b.subtitle) return false
  if (a.body !== b.body) return false
  if (a.isDraft !== b.isDraft) return false
  if (a.labels.length !== b.labels.length) return false
  for (let i = 0; i < a.labels.length; i++) {
    if (a.labels[i] !== b.labels[i]) return false
  }
  return true
}

function readDraft(key: string): DraftData | null {
  try {
    const stored = localStorage.getItem(key)
    if (stored !== null) {
      const parsed = JSON.parse(stored) as Partial<DraftData>
      if (parsed._v !== DRAFT_SCHEMA_VERSION) return null
      return {
        title: typeof parsed.title === 'string' ? parsed.title : '',
        subtitle: typeof parsed.subtitle === 'string' ? parsed.subtitle : '',
        body: typeof parsed.body === 'string' ? parsed.body : '',
        labels: Array.isArray(parsed.labels) ? parsed.labels.filter((label) => typeof label === 'string') : [],
        isDraft: parsed.isDraft === true,
        _v: DRAFT_SCHEMA_VERSION,
        ...(typeof parsed.savedAt === 'string' ? { savedAt: parsed.savedAt } : {}),
      }
    }
  } catch {
    // Ignore invalid JSON
  }
  return null
}

function persistDraft(key: string, draft: DraftData): void {
  try {
    localStorage.setItem(key, JSON.stringify({ ...draft, _v: DRAFT_SCHEMA_VERSION }))
  } catch {
    // Ignore storage quota / privacy mode failures and keep editing session alive.
  }
}

function deleteDraft(key: string): void {
  try {
    localStorage.removeItem(key)
  } catch {
    // Ignore storage failures so discard/save never crash the editor.
  }
}

export function useEditorAutoSave({
  key,
  currentState,
  onRestore,
  enabled = true,
}: UseEditorAutoSaveParams): UseEditorAutoSaveReturn {
  // Use state (not ref) so changes trigger isDirty recalculation
  const [savedState, setSavedState] = useState<DraftData>(currentState)

  // Ref to skip the navigation blocker after a successful save
  const navigationAllowedRef = useRef(false)

  const onRestoreRef = useRef(onRestore)
  useEffect(() => {
    onRestoreRef.current = onRestore
  }, [onRestore])

  // Keep a ref to currentState so markSaved always has the latest value
  const currentStateRef = useRef(currentState)
  useEffect(() => {
    currentStateRef.current = currentState
  }, [currentState])

  // Track enabled transitions: when enabled becomes true, capture current state as baseline
  const prevEnabledRef = useRef(enabled)
  useEffect(() => {
    if (enabled && !prevEnabledRef.current) {
      setSavedState(currentStateRef.current)
    }
    prevEnabledRef.current = enabled
  }, [enabled])

  // Draft recovery: read from localStorage synchronously on init
  const storedDraft = useMemo(() => readDraft(key), [key])
  const [draftOverride, setDraftOverride] = useState<{
    key: string
    draft: DraftData | null
  } | null>(null)
  const draftData = draftOverride?.key === key ? draftOverride.draft : storedDraft
  const draftAvailable = draftData !== null
  const draftSavedAt = draftData?.savedAt ?? null

  const isDirty = useMemo(
    () => enabled && !statesEqual(currentState, savedState),
    [enabled, currentState, savedState],
  )

  // Debounced auto-save to localStorage
  useEffect(() => {
    if (!isDirty) return

    const timer = setTimeout(() => {
      const toSave: DraftData = {
        ...currentState,
        savedAt: new Date().toISOString(),
      }
      persistDraft(key, toSave)
    }, AUTO_SAVE_DEBOUNCE_MS)

    return () => clearTimeout(timer)
  }, [isDirty, currentState, key])

  // beforeunload handler
  useEffect(() => {
    if (!isDirty) return

    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault()
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [isDirty])

  // react-router navigation blocking
  const blocker = useBlocker(isDirty)

  useEffect(() => {
    if (blocker.state === 'blocked') {
      if (navigationAllowedRef.current) {
        navigationAllowedRef.current = false
        blocker.proceed()
        return
      }
      const leave = window.confirm('You have unsaved changes. Are you sure you want to leave?')
      if (leave) {
        blocker.proceed()
      } else {
        blocker.reset()
      }
    }
  }, [blocker])

  const restoreDraft = useCallback(() => {
    if (draftData) {
      onRestoreRef.current(draftData)
      setSavedState(draftData)
    }
    setDraftOverride({ key, draft: null })
  }, [draftData, key])

  const discardDraft = useCallback(() => {
    deleteDraft(key)
    setDraftOverride({ key, draft: null })
  }, [key])

  const markSaved = useCallback(() => {
    deleteDraft(key)
    setSavedState(currentStateRef.current)
    setDraftOverride({ key, draft: null })
    navigationAllowedRef.current = true
  }, [key])

  return {
    isDirty,
    draftAvailable,
    draftSavedAt,
    restoreDraft,
    discardDraft,
    markSaved,
  }
}
