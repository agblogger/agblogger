import { create } from 'zustand'
import type { UserResponse } from '@/api/client'
import { HTTPError } from '@/api/client'
import { fetchMe, login as apiLogin, logout as apiLogout } from '@/api/auth'

interface AuthState {
  user: UserResponse | null
  isLoading: boolean
  isLoggingOut: boolean
  isInitialized: boolean
  error: string | null
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
  checkAuth: () => Promise<void>
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isLoading: false,
  isLoggingOut: false,
  isInitialized: false,
  error: null,

  login: async (username: string, password: string) => {
    set({ isLoading: true, error: null })
    try {
      await apiLogin(username, password)
      const user = await fetchMe()
      set({ user, isLoading: false })
    } catch (err) {
      const message =
        err instanceof HTTPError && err.response.status === 401
          ? 'Invalid credentials'
          : 'Login failed. Please try again.'
      set({ error: message, isLoading: false })
      throw new Error('Login failed')
    }
  },

  logout: async () => {
    set({ isLoggingOut: true })
    try {
      await apiLogout()
    } catch (err) {
      console.error('Logout failed:', err)
    } finally {
      set({ user: null, isLoggingOut: false })
    }
  },

  checkAuth: async () => {
    try {
      const user = await fetchMe()
      set({ user, isInitialized: true })
    } catch (err) {
      if (!(err instanceof HTTPError) || err.response.status !== 401) {
        console.error('Auth check failed:', err)
      }
      set({ user: null, isInitialized: true })
    }
  },
}))
