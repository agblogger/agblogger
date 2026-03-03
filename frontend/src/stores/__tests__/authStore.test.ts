import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MockHTTPError } from '@/test/MockHTTPError'

const mockFetchMe = vi.fn()
const mockApiLogin = vi.fn()
const mockApiLogout = vi.fn()

vi.mock('@/api/auth', () => ({
  fetchMe: (...args: unknown[]) => mockFetchMe(...args) as unknown,
  login: (...args: unknown[]) => mockApiLogin(...args) as unknown,
  logout: (...args: unknown[]) => mockApiLogout(...args) as unknown,
}))

vi.mock('@/api/client', async () => {
  const { MockHTTPError } = await import('@/test/MockHTTPError')
  return {
    HTTPError: MockHTTPError,
  }
})

// Import after mocks are set up
const { useAuthStore } = await import('@/stores/authStore')

const testUser = {
  id: 1,
  username: 'admin',
  email: 'admin@test.com',
  display_name: 'Admin',
  is_admin: true,
}

describe('authStore', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useAuthStore.setState({ user: null, isLoading: false, isLoggingOut: false, error: null })
  })

  describe('checkAuth', () => {
    it('401 sets user to null', async () => {
      mockFetchMe.mockRejectedValue(new MockHTTPError(401))

      await useAuthStore.getState().checkAuth()
      expect(useAuthStore.getState().user).toBeNull()
    })

    it('success sets user', async () => {
      mockFetchMe.mockResolvedValue(testUser)

      await useAuthStore.getState().checkAuth()
      expect(useAuthStore.getState().user).toEqual(testUser)
    })

    it('non-401 error clears user and logs error', async () => {
      const error = new Error('Network failure')
      mockFetchMe.mockRejectedValue(error)
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

      await useAuthStore.getState().checkAuth()
      expect(useAuthStore.getState().user).toBeNull()
      expect(consoleSpy).toHaveBeenCalledWith('Auth check failed:', error)
      consoleSpy.mockRestore()
    })
  })

  describe('login', () => {
    it('success sets user', async () => {
      mockApiLogin.mockResolvedValue({
        csrf_token: 'csrf',
      })
      mockFetchMe.mockResolvedValue(testUser)

      await useAuthStore.getState().login('admin', 'password')
      expect(useAuthStore.getState().user).toEqual(testUser)
      expect(useAuthStore.getState().isLoading).toBe(false)
    })

    it('401 shows invalid credentials message', async () => {
      mockApiLogin.mockRejectedValue(new MockHTTPError(401))

      await expect(useAuthStore.getState().login('bad', 'creds')).rejects.toThrow('Login failed')
      expect(useAuthStore.getState().error).toBe('Invalid username or password')
    })

    it('generic error shows generic message', async () => {
      mockApiLogin.mockRejectedValue(new Error('Network'))

      await expect(useAuthStore.getState().login('admin', 'pass')).rejects.toThrow('Login failed')
      expect(useAuthStore.getState().error).toBe('Login failed. Please try again.')
    })
  })

  describe('logout', () => {
    it('clears user and calls apiLogout', async () => {
      mockApiLogout.mockResolvedValue(undefined)
      useAuthStore.setState({ user: testUser })

      await useAuthStore.getState().logout()
      expect(useAuthStore.getState().user).toBeNull()
      expect(mockApiLogout).toHaveBeenCalled()
    })
  })
})
