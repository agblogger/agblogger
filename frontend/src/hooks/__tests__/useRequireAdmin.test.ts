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

import { useRequireAdmin } from '../useRequireAdmin'

const testUser: UserResponse = {
  id: 1,
  username: 'admin',
  email: 'admin@test.com',
  display_name: null,
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

describe('useRequireAdmin', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUser = testUser
    mockIsInitialized = true
  })

  describe('isReady', () => {
    it('returns isReady: false when auth store is not initialized', () => {
      mockIsInitialized = false
      const { result } = renderHook(() => useRequireAdmin(), { wrapper: createWrapper() })
      expect(result.current.isReady).toBe(false)
    })

    it('returns isReady: false when user is null', () => {
      mockUser = null
      const { result } = renderHook(() => useRequireAdmin(), { wrapper: createWrapper() })
      expect(result.current.isReady).toBe(false)
    })

    it('returns isReady: true for authenticated user', () => {
      const { result } = renderHook(() => useRequireAdmin(), { wrapper: createWrapper() })
      expect(result.current.isReady).toBe(true)
    })
  })

  describe('user', () => {
    it('returns the current user', () => {
      const { result } = renderHook(() => useRequireAdmin(), { wrapper: createWrapper() })
      expect(result.current.user).toBe(testUser)
    })

    it('returns null when not authenticated', () => {
      mockUser = null
      const { result } = renderHook(() => useRequireAdmin(), { wrapper: createWrapper() })
      expect(result.current.user).toBeNull()
    })
  })

  describe('redirects', () => {
    it('redirects to /login when user is null and initialized', () => {
      mockUser = null
      mockIsInitialized = true
      renderHook(() => useRequireAdmin(), { wrapper: createWrapper() })
      expect(mockNavigate).toHaveBeenCalledWith('/login', { replace: true })
    })

    it('does not redirect when auth store is not yet initialized', () => {
      mockUser = null
      mockIsInitialized = false
      renderHook(() => useRequireAdmin(), { wrapper: createWrapper() })
      expect(mockNavigate).not.toHaveBeenCalled()
    })

    it('does not redirect authenticated user', () => {
      mockIsInitialized = true
      renderHook(() => useRequireAdmin(), { wrapper: createWrapper() })
      expect(mockNavigate).not.toHaveBeenCalled()
    })
  })
})
