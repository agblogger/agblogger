import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/stores/authStore'
import type { UserResponse } from '@/api/client'

/**
 * Redirects unauthenticated users to /login (or non-admin users to /) and
 * returns the current auth state so the caller can render a guard.
 *
 * Usage:
 * ```ts
 * const { user, isReady } = useRequireAuth()
 * // ... hooks that may reference `user` via optional chaining ...
 * if (!isReady) return null
 * // user is guaranteed non-null past this point
 * ```
 */
export function useRequireAuth(options?: { requireAdmin?: boolean }): {
  user: UserResponse | null
  isReady: boolean
} {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const isInitialized = useAuthStore((s) => s.isInitialized)
  const requireAdmin = options?.requireAdmin ?? false

  useEffect(() => {
    if (!isInitialized) return
    if (!user) {
      void navigate('/login', { replace: true })
    } else if (requireAdmin && !user.is_admin) {
      void navigate('/', { replace: true })
    }
  }, [user, isInitialized, navigate, requireAdmin])

  const isReady = isInitialized && user !== null && (!requireAdmin || user.is_admin)

  return { user, isReady }
}
