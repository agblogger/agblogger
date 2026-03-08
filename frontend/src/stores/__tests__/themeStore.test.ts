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
  useThemeStore.setState({ theme: 'light' })
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
  it('initializes with system light theme by default', () => {
    useThemeStore.getState().init()
    expect(useThemeStore.getState().theme).toBe('light')
    expect(document.documentElement.classList.contains('dark')).toBe(false)
  })

  it('initializes with system dark theme when prefers-color-scheme is dark', () => {
    darkMediaMatches = true
    useThemeStore.getState().init()
    expect(useThemeStore.getState().theme).toBe('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })

  it('reads stored theme from localStorage', () => {
    storage['agblogger:theme'] = 'dark'
    useThemeStore.getState().init()
    expect(useThemeStore.getState().theme).toBe('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })

  it('toggles light → dark → light', () => {
    useThemeStore.getState().init()
    expect(useThemeStore.getState().theme).toBe('light')

    useThemeStore.getState().toggleTheme()
    expect(useThemeStore.getState().theme).toBe('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)

    useThemeStore.getState().toggleTheme()
    expect(useThemeStore.getState().theme).toBe('light')
    expect(document.documentElement.classList.contains('dark')).toBe(false)
  })

  it('saves to localStorage only when choice differs from system theme', () => {
    // System is light
    useThemeStore.getState().init()

    // Toggle to dark (differs from system) → should save
    useThemeStore.getState().toggleTheme()
    expect(storage['agblogger:theme']).toBe('dark')

    // Toggle back to light (matches system) → should remove
    useThemeStore.getState().toggleTheme()
    expect(storage['agblogger:theme']).toBeUndefined()
  })

  it('removes localStorage when toggling back to system default', () => {
    darkMediaMatches = true // system is dark
    useThemeStore.getState().init()

    // Toggle to light (differs from system) → should save
    useThemeStore.getState().toggleTheme()
    expect(storage['agblogger:theme']).toBe('light')

    // Toggle back to dark (matches system) → should remove
    useThemeStore.getState().toggleTheme()
    expect(storage['agblogger:theme']).toBeUndefined()
  })

  it('reacts to system theme changes when no stored preference', () => {
    useThemeStore.getState().init()
    expect(useThemeStore.getState().theme).toBe('light')

    darkMediaMatches = true
    for (const listener of listeners) listener()
    expect(useThemeStore.getState().theme).toBe('dark')
  })

  it('ignores system theme changes when user has stored preference', () => {
    storage['agblogger:theme'] = 'light'
    useThemeStore.getState().init()

    darkMediaMatches = true
    for (const listener of listeners) listener()
    expect(useThemeStore.getState().theme).toBe('light')
  })

  it('ignores invalid localStorage values and uses system theme', () => {
    storage['agblogger:theme'] = 'invalid'
    useThemeStore.getState().init()
    expect(useThemeStore.getState().theme).toBe('light')
  })

  it('falls back to system theme when localStorage.getItem throws', () => {
    const throwingStorage = Object.create(fakeLocalStorage) as Storage
    throwingStorage.getItem = () => { throw new DOMException('blocked', 'SecurityError') }
    vi.stubGlobal('localStorage', throwingStorage)

    useThemeStore.getState().init()
    expect(useThemeStore.getState().theme).toBe('light')
  })

  it('returns a cleanup function from init that removes the MQL listener', () => {
    const removeSpy = vi.fn()
    vi.stubGlobal('matchMedia', (query: string) =>
      Object.assign(makeMql(query), { removeEventListener: removeSpy }),
    )

    const cleanup = useThemeStore.getState().init()
    expect(typeof cleanup).toBe('function')
    cleanup()
    expect(removeSpy).toHaveBeenCalledWith('change', expect.any(Function))
  })

  it('still updates state when localStorage throws in toggleTheme', () => {
    const throwingStorage = Object.create(fakeLocalStorage) as Storage
    throwingStorage.setItem = () => { throw new DOMException('quota exceeded', 'QuotaExceededError') }
    throwingStorage.removeItem = () => { throw new DOMException('quota exceeded', 'QuotaExceededError') }
    vi.stubGlobal('localStorage', throwingStorage)

    useThemeStore.getState().init()
    expect(useThemeStore.getState().theme).toBe('light')

    expect(() => useThemeStore.getState().toggleTheme()).not.toThrow()
    expect(useThemeStore.getState().theme).toBe('dark')
  })
})
