import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/stores/authStore'
import type { UserResponse } from '@/api/client'

type AdminGuardResult =
  | { isReady: false; user: null }
  | { isReady: true; user: UserResponse }

/**
 * Redirects to /login when not authenticated as the admin and returns the current auth state
 * so the caller can render a guard.
 *
 * The return type is a discriminated union: after checking `if (!isReady) return null`,
 * TypeScript narrows `user` to `UserResponse` (non-null) automatically.
 *
 * Usage:
 * ```ts
 * const { user, isReady } = useRequireAdmin()
 * // ... hooks that may reference `user` via optional chaining ...
 * if (!isReady) return null
 * // user is guaranteed non-null past this point
 * ```
 */
export function useRequireAdmin(): AdminGuardResult {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const isInitialized = useAuthStore((s) => s.isInitialized)

  useEffect(() => {
    if (!isInitialized) return
    if (!user) {
      void navigate('/login', { replace: true })
    }
  }, [user, isInitialized, navigate])

  if (isInitialized && user !== null) {
    return { user, isReady: true }
  }
  return { user: null, isReady: false }
}
