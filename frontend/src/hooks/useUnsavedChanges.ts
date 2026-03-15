import { useEffect, useRef } from 'react'
import { useBlocker } from 'react-router-dom'

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

  return {
    markSaved: () => {
      navigationAllowedRef.current = true
    },
  }
}
