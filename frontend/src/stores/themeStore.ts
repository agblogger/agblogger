import { create } from 'zustand'

type ThemeMode = 'light' | 'dark' | 'system'

interface ThemeState {
  mode: ThemeMode
  resolvedTheme: 'light' | 'dark'
  toggleMode: () => void
  init: () => void
}

const STORAGE_KEY = 'agblogger:theme'

const CYCLE: Record<ThemeMode, ThemeMode> = {
  system: 'light',
  light: 'dark',
  dark: 'system',
}

function getSystemTheme(): 'light' | 'dark' {
  if (typeof window === 'undefined') return 'light'
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function resolveTheme(mode: ThemeMode): 'light' | 'dark' {
  return mode === 'system' ? getSystemTheme() : mode
}

function applyTheme(resolved: 'light' | 'dark') {
  if (typeof document === 'undefined') return
  document.documentElement.classList.toggle('dark', resolved === 'dark')
}

export const useThemeStore = create<ThemeState>((set, get) => ({
  mode: 'system',
  resolvedTheme: 'light',

  toggleMode: () => {
    const next = CYCLE[get().mode]
    const resolved = resolveTheme(next)
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // Silently ignore — private browsing or quota exceeded
    }
    applyTheme(resolved)
    set({ mode: next, resolvedTheme: resolved })
  },

  init: () => {
    let stored: ThemeMode | null
    try {
      stored = localStorage.getItem(STORAGE_KEY) as ThemeMode | null
    } catch {
      stored = null
    }
    const mode: ThemeMode = stored === 'light' || stored === 'dark' || stored === 'system'
      ? stored
      : 'system'
    const resolved = resolveTheme(mode)
    applyTheme(resolved)
    set({ mode, resolvedTheme: resolved })

    const mql = window.matchMedia('(prefers-color-scheme: dark)')
    mql.addEventListener('change', () => {
      const current = get().mode
      if (current === 'system') {
        const newResolved = getSystemTheme()
        applyTheme(newResolved)
        set({ resolvedTheme: newResolved })
      }
    })
  },
}))
