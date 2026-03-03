import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { useThemeStore } from '../themeStore'

let darkMediaMatches = false
const listeners: Array<() => void> = []
let storage: Record<string, string> = {}

function makeMql(query: string): MediaQueryList {
  return {
    matches: query === '(prefers-color-scheme: dark)' ? darkMediaMatches : false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: (_: string, cb: () => void) => { listeners.push(cb) },
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  } as unknown as MediaQueryList
}

const fakeLocalStorage = {
  getItem: (key: string) => storage[key] ?? null,
  setItem: (key: string, value: string) => { storage[key] = value },
  removeItem: (key: string) => { const { [key]: _, ...rest } = storage; void _; storage = rest },
  clear: () => { storage = {} },
  get length() { return Object.keys(storage).length },
  key: (_index: number) => null,
} as Storage

beforeEach(() => {
  useThemeStore.setState({ mode: 'system', resolvedTheme: 'light' })
  document.documentElement.classList.remove('dark')
  darkMediaMatches = false
  listeners.length = 0
  storage = {}

  vi.stubGlobal('localStorage', fakeLocalStorage)
  vi.stubGlobal('matchMedia', (query: string) => makeMql(query))
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('themeStore', () => {
  it('initializes with system mode by default', () => {
    useThemeStore.getState().init()
    expect(useThemeStore.getState().mode).toBe('system')
  })

  it('reads stored mode from localStorage', () => {
    storage['agblogger:theme'] = 'dark'
    useThemeStore.getState().init()
    expect(useThemeStore.getState().mode).toBe('dark')
    expect(useThemeStore.getState().resolvedTheme).toBe('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })

  it('toggles system → light → dark → system', () => {
    useThemeStore.getState().init()
    expect(useThemeStore.getState().mode).toBe('system')

    useThemeStore.getState().toggleMode()
    expect(useThemeStore.getState().mode).toBe('light')
    expect(storage['agblogger:theme']).toBe('light')

    useThemeStore.getState().toggleMode()
    expect(useThemeStore.getState().mode).toBe('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)

    useThemeStore.getState().toggleMode()
    expect(useThemeStore.getState().mode).toBe('system')
  })

  it('resolves system mode based on prefers-color-scheme', () => {
    darkMediaMatches = true
    useThemeStore.getState().init()
    expect(useThemeStore.getState().resolvedTheme).toBe('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })

  it('reacts to system theme changes when in system mode', () => {
    useThemeStore.getState().init()
    expect(useThemeStore.getState().resolvedTheme).toBe('light')

    darkMediaMatches = true
    for (const listener of listeners) listener()
    expect(useThemeStore.getState().resolvedTheme).toBe('dark')
  })

  it('ignores system theme changes when not in system mode', () => {
    storage['agblogger:theme'] = 'light'
    useThemeStore.getState().init()

    darkMediaMatches = true
    for (const listener of listeners) listener()
    expect(useThemeStore.getState().resolvedTheme).toBe('light')
  })

  it('ignores invalid localStorage values', () => {
    storage['agblogger:theme'] = 'invalid'
    useThemeStore.getState().init()
    expect(useThemeStore.getState().mode).toBe('system')
  })
})
