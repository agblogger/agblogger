import { create } from 'zustand'
import type { SiteConfigResponse } from '@/api/client'
import api from '@/api/client'

interface SiteState {
  config: SiteConfigResponse | null
  isLoading: boolean
  error: string | null
  fetchConfig: () => Promise<void>
}

/** Fire-and-forget config refresh — safe to call from event handlers. */
export function refreshSiteConfig(onError?: (msg: string) => void): void {
  useSiteStore.getState().fetchConfig().then(() => {
    const { error } = useSiteStore.getState()
    if (error !== null) {
      console.warn('Failed to refresh site config')
      onError?.('Site configuration may be stale. Reload the page to see latest changes.')
    }
  }).catch((err: unknown) => {
    // fetchConfig catches internally, so this is a safety net for unexpected rejections
    console.warn('Failed to refresh site config', err)
    onError?.('Site configuration may be stale. Reload the page to see latest changes.')
  })
}

export const useSiteStore = create<SiteState>((set) => ({
  config: null,
  isLoading: false,
  error: null,

  fetchConfig: async () => {
    set({ isLoading: true, error: null })
    try {
      const config = await api.get('pages').json<SiteConfigResponse>()
      set({ config, isLoading: false })
    } catch (err) {
      console.error('fetchConfig failed:', err)
      set({ isLoading: false, error: 'Failed to load site configuration' })
    }
  },
}))
