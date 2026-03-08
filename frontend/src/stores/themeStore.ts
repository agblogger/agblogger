import { create } from 'zustand'

type Theme = 'light' | 'dark'

interface ThemeState {
  theme: Theme
  toggleTheme: () => void
  init: () => () => void
}

const STORAGE_KEY = 'agblogger:theme'

function getSystemTheme(): Theme {
  if (typeof window === 'undefined') return 'light'
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function applyTheme(theme: Theme) {
  if (typeof document === 'undefined') return
  document.documentElement.classList.toggle('dark', theme === 'dark')
}

export const useThemeStore = create<ThemeState>((set, get) => ({
  theme: 'light',

  toggleTheme: () => {
    const next: Theme = get().theme === 'light' ? 'dark' : 'light'
    try {
      if (next === getSystemTheme()) {
        localStorage.removeItem(STORAGE_KEY)
      } else {
        localStorage.setItem(STORAGE_KEY, next)
      }
    } catch {
      // Silently ignore — private browsing or quota exceeded
    }
    applyTheme(next)
    set({ theme: next })
  },

  init: () => {
    let stored: string | null
    try {
      stored = localStorage.getItem(STORAGE_KEY)
    } catch {
      stored = null
    }
    const theme: Theme = stored === 'light' || stored === 'dark' ? stored : getSystemTheme()
    applyTheme(theme)
    set({ theme })

    const mql = window.matchMedia('(prefers-color-scheme: dark)')
    const handler = () => {
      let hasStored: boolean
      try {
        hasStored = localStorage.getItem(STORAGE_KEY) !== null
      } catch {
        hasStored = false
      }
      if (!hasStored) {
        const newTheme = getSystemTheme()
        applyTheme(newTheme)
        set({ theme: newTheme })
      }
    }
    mql.addEventListener('change', handler)
    return () => mql.removeEventListener('change', handler)
  },
}))
