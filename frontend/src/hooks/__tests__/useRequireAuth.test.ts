import { renderHook } from '@testing-library/react'
import { createElement } from 'react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { ReactNode } from 'react'

import type { UserResponse } from '@/api/client'

let mockUser: UserResponse | null = null
let mockIsInitialized = true

vi.mock('@/stores/authStore', () => ({
  useAuthStore: (selector: (s: { user: UserResponse | null; isInitialized: boolean }) => unknown) =>
    selector({ user: mockUser, isInitialized: mockIsInitialized }),
}))

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

import { useRequireAuth } from '../useRequireAuth'

const adminUser: UserResponse = {
  id: 1,
  username: 'admin',
  email: 'admin@test.com',
  display_name: null,
  is_admin: true,
}

const regularUser: UserResponse = {
  id: 2,
  username: 'author',
  email: 'author@test.com',
  display_name: null,
  is_admin: false,
}

function createWrapper() {
  return function Wrapper({ children }: { children: ReactNode }) {
    const router = createMemoryRouter(
      [{ path: '/', element: children }],
      { initialEntries: ['/'] },
    )
    return createElement(RouterProvider, { router })
  }
}

describe('useRequireAuth', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUser = adminUser
    mockIsInitialized = true
  })

  describe('isReady', () => {
    it('returns isReady: false when auth store is not initialized', () => {
      mockIsInitialized = false
      const { result } = renderHook(() => useRequireAuth(), { wrapper: createWrapper() })
      expect(result.current.isReady).toBe(false)
    })

    it('returns isReady: false when user is null', () => {
      mockUser = null
      const { result } = renderHook(() => useRequireAuth(), { wrapper: createWrapper() })
      expect(result.current.isReady).toBe(false)
    })

    it('returns isReady: true for authenticated user without requireAdmin', () => {
      mockUser = regularUser
      const { result } = renderHook(() => useRequireAuth(), { wrapper: createWrapper() })
      expect(result.current.isReady).toBe(true)
    })

    it('returns isReady: true for admin when requireAdmin is true', () => {
      mockUser = adminUser
      const { result } = renderHook(
        () => useRequireAuth({ requireAdmin: true }),
        { wrapper: createWrapper() },
      )
      expect(result.current.isReady).toBe(true)
    })

    it('returns isReady: false for non-admin when requireAdmin is true', () => {
      mockUser = regularUser
      const { result } = renderHook(
        () => useRequireAuth({ requireAdmin: true }),
        { wrapper: createWrapper() },
      )
      expect(result.current.isReady).toBe(false)
    })
  })

  describe('user', () => {
    it('returns the current user', () => {
      mockUser = adminUser
      const { result } = renderHook(() => useRequireAuth(), { wrapper: createWrapper() })
      expect(result.current.user).toBe(adminUser)
    })

    it('returns null when not authenticated', () => {
      mockUser = null
      const { result } = renderHook(() => useRequireAuth(), { wrapper: createWrapper() })
      expect(result.current.user).toBeNull()
    })
  })

  describe('redirects', () => {
    it('redirects to /login when user is null and initialized', () => {
      mockUser = null
      mockIsInitialized = true
      renderHook(() => useRequireAuth(), { wrapper: createWrapper() })
      expect(mockNavigate).toHaveBeenCalledWith('/login', { replace: true })
    })

    it('does not redirect when auth store is not yet initialized', () => {
      mockUser = null
      mockIsInitialized = false
      renderHook(() => useRequireAuth(), { wrapper: createWrapper() })
      expect(mockNavigate).not.toHaveBeenCalled()
    })

    it('redirects non-admin to / when requireAdmin is true', () => {
      mockUser = regularUser
      mockIsInitialized = true
      renderHook(
        () => useRequireAuth({ requireAdmin: true }),
        { wrapper: createWrapper() },
      )
      expect(mockNavigate).toHaveBeenCalledWith('/', { replace: true })
    })

    it('does not redirect admin when requireAdmin is true', () => {
      mockUser = adminUser
      mockIsInitialized = true
      renderHook(
        () => useRequireAuth({ requireAdmin: true }),
        { wrapper: createWrapper() },
      )
      expect(mockNavigate).not.toHaveBeenCalled()
    })

    it('does not redirect authenticated user without requireAdmin', () => {
      mockUser = regularUser
      mockIsInitialized = true
      renderHook(() => useRequireAuth(), { wrapper: createWrapper() })
      expect(mockNavigate).not.toHaveBeenCalled()
    })
  })
})
