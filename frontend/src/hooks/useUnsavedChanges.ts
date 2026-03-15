import { useCallback, useEffect, useMemo, useRef } from 'react'
import { useBlocker } from 'react-router-dom'

/**
 * Guards against accidental navigation away from pages with unsaved changes.
 *
 * Two-pronged guard strategy:
 * - **React Router blocker**: calls `useBlocker(isDirty)` to intercept in-app navigation.
 *   When a navigation attempt is blocked, the user is shown a `window.confirm` dialog.
 *   They can proceed or cancel. This covers Link clicks, programmatic `navigate()` calls,
 *   and browser back/forward within the SPA.
 * - **beforeunload listener**: attached whenever `isDirty` is true and removed when it
 *   becomes false. This covers browser tab close, page refresh, and hard navigation away
 *   from the app.
 *
 * ### Why `markSaved()` exists
 *
 * When a consumer saves successfully and then immediately triggers navigation in the same
 * synchronous block (e.g. `markSaved(); navigate('/somewhere')`), React has not yet
 * re-rendered. The `isDirty` value captured by `useBlocker` is therefore still `true`,
 * so the blocker fires and would incorrectly show the confirm dialog even though the data
 * was just saved.
 *
 * `markSaved()` sets an internal ref (not state) that the blocker effect checks before
 * prompting. If the ref is set, the next blocked navigation is allowed through without a
 * dialog and the ref is cleared. The ref is also reset whenever `isDirty` becomes `true`
 * again, so a re-dirtied form is never silently bypassed.
 *
 * ### Usage
 *
 * ```ts
 * const { markSaved } = useUnsavedChanges(isDirty)
 *
 * async function handleSave() {
 *   await api.save(...)
 *   setIsDirty(false)   // queues a re-render
 *   markSaved()         // sets the ref immediately, before the re-render
 *   navigate('/posts')  // navigation proceeds without the confirm dialog
 * }
 * ```
 *
 * Call `markSaved()` then trigger navigation in the **same synchronous block**. Do not
 * await anything between the two calls or the timing guarantee is lost.
 */
export function useUnsavedChanges(isDirty: boolean): { markSaved: () => void } {
  const navigationAllowedRef = useRef(false)

  useEffect(() => {
    if (isDirty) {
      navigationAllowedRef.current = false
    }
  }, [isDirty])

  useEffect(() => {
    if (!isDirty) return

    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault()
      e.returnValue = ''
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [isDirty])

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

  const markSaved = useCallback(() => {
    navigationAllowedRef.current = true
  }, [])

  return useMemo(() => ({ markSaved }), [markSaved])
}
