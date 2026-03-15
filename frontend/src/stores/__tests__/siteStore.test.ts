import { describe, it, expect, vi, beforeEach } from 'vitest'

const mockApiGet = vi.fn()

vi.mock('@/api/client', () => ({
  default: { get: () => ({ json: () => mockApiGet() as unknown }) },
}))

const { useSiteStore, refreshSiteConfig } = await import('@/stores/siteStore')

describe('siteStore', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useSiteStore.setState({ config: null, isLoading: false, error: null })
  })

  it('has correct initial state', () => {
    const state = useSiteStore.getState()
    expect(state.config).toBeNull()
    expect(state.isLoading).toBe(false)
    expect(state.error).toBeNull()
  })

  it('fetchConfig sets config on success', async () => {
    const config = { title: 'Test', description: 'Blog', pages: [] }
    mockApiGet.mockResolvedValue(config)

    await useSiteStore.getState().fetchConfig()

    const state = useSiteStore.getState()
    expect(state.config).toEqual(config)
    expect(state.isLoading).toBe(false)
    expect(state.error).toBeNull()
  })

  it('fetchConfig sets error on failure', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    mockApiGet.mockRejectedValue(new Error('Network'))

    await useSiteStore.getState().fetchConfig()

    const state = useSiteStore.getState()
    expect(state.config).toBeNull()
    expect(state.isLoading).toBe(false)
    expect(state.error).toBe('Failed to load site configuration')
  })

  it('fetchConfig sets isLoading during fetch', async () => {
    let resolvePromise: (v: unknown) => void
    mockApiGet.mockReturnValue(new Promise((r) => { resolvePromise = r }))

    const promise = useSiteStore.getState().fetchConfig()

    expect(useSiteStore.getState().isLoading).toBe(true)

    resolvePromise!({ title: 'T', description: '', pages: [] })
    await promise

    expect(useSiteStore.getState().isLoading).toBe(false)
  })

  it('fetchConfig logs the error with console.error on failure', async () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const error = new Error('Network')
    mockApiGet.mockRejectedValue(error)

    await useSiteStore.getState().fetchConfig()

    expect(consoleSpy).toHaveBeenCalledWith('fetchConfig failed:', error)
    consoleSpy.mockRestore()
  })

  describe('refreshSiteConfig', () => {
    it('calls onError callback with a message when refresh fails', async () => {
      mockApiGet.mockRejectedValue(new Error('Network'))
      vi.spyOn(console, 'error').mockImplementation(() => {})
      vi.spyOn(console, 'warn').mockImplementation(() => {})

      const onError = vi.fn()
      refreshSiteConfig(onError)

      // Wait for the async fetch + then to complete
      await new Promise((r) => setTimeout(r, 0))

      expect(onError).toHaveBeenCalledWith(
        'Site configuration may be stale. Reload the page to see latest changes.',
      )
    })

    it('does not throw when no onError callback is provided and refresh fails', async () => {
      mockApiGet.mockRejectedValue(new Error('Network'))
      vi.spyOn(console, 'error').mockImplementation(() => {})
      vi.spyOn(console, 'warn').mockImplementation(() => {})

      expect(() => refreshSiteConfig()).not.toThrow()

      // Wait for the async fetch + then to complete
      await new Promise((r) => setTimeout(r, 0))
    })

    it('does not call onError when refresh succeeds', async () => {
      const config = { title: 'Test', description: 'Blog', pages: [] }
      mockApiGet.mockResolvedValue(config)

      const onError = vi.fn()
      refreshSiteConfig(onError)

      // Wait for the async fetch to complete
      await new Promise((r) => setTimeout(r, 0))

      expect(onError).not.toHaveBeenCalled()
    })
  })
})
