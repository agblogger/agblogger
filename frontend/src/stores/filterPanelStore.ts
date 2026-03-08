import { create } from 'zustand'

type PanelState = 'closed' | 'open' | 'closing'

interface FilterPanelState {
  panelState: PanelState
  activeFilterCount: number
  togglePanel: () => void
  closePanel: () => void
  onAnimationEnd: () => void
  setActiveFilterCount: (count: number) => void
}

export const useFilterPanelStore = create<FilterPanelState>((set, get) => ({
  panelState: 'closed',
  activeFilterCount: 0,

  togglePanel: () => {
    const current = get().panelState
    if (current === 'closed' || current === 'closing') {
      set({ panelState: 'open' })
    } else {
      set({ panelState: 'closing' })
    }
  },

  closePanel: () => {
    if (get().panelState === 'open') {
      set({ panelState: 'closing' })
    }
  },

  onAnimationEnd: () => {
    if (get().panelState === 'closing') {
      set({ panelState: 'closed' })
    }
  },

  setActiveFilterCount: (count: number) => set({ activeFilterCount: count }),
}))
