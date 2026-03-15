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
export function refreshSiteConfig(): void {
  useSiteStore.getState().fetchConfig().catch((err: unknown) => {
    console.warn('Failed to refresh site config', err)
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
    } catch {
      set({ isLoading: false, error: 'Failed to load site configuration' })
    }
  },
}))
