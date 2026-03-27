import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/stores/authStore'
import type { UserResponse } from '@/api/client'

/**
 * Redirects unauthenticated users to /login and returns the current auth state
 * so the caller can render a guard.
 *
 * Usage:
 * ```ts
 * const { user, isReady } = useRequireAdmin()
 * // ... hooks that may reference `user` via optional chaining ...
 * if (!isReady) return null
 * // user is guaranteed non-null past this point
 * ```
 */
export function useRequireAdmin(): {
  user: UserResponse | null
  isReady: boolean
} {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const isInitialized = useAuthStore((s) => s.isInitialized)

  useEffect(() => {
    if (!isInitialized) return
    if (!user) {
      void navigate('/login', { replace: true })
    }
  }, [user, isInitialized, navigate])

  const isReady = isInitialized && user !== null

  return { user, isReady }
}
