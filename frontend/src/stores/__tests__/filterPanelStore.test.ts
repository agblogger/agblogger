import { describe, it, expect, beforeEach } from 'vitest'
import { useFilterPanelStore } from '../filterPanelStore'

describe('filterPanelStore', () => {
  beforeEach(() => {
    useFilterPanelStore.setState({
      panelState: 'closed',
      activeFilterCount: 0,
    })
  })

  it('starts closed with zero active filters', () => {
    const state = useFilterPanelStore.getState()
    expect(state.panelState).toBe('closed')
    expect(state.activeFilterCount).toBe(0)
  })

  it('togglePanel opens from closed', () => {
    useFilterPanelStore.getState().togglePanel()
    expect(useFilterPanelStore.getState().panelState).toBe('open')
  })

  it('togglePanel starts closing from open', () => {
    useFilterPanelStore.setState({ panelState: 'open' })
    useFilterPanelStore.getState().togglePanel()
    expect(useFilterPanelStore.getState().panelState).toBe('closing')
  })

  it('togglePanel opens from closing (re-open during animation)', () => {
    useFilterPanelStore.setState({ panelState: 'closing' })
    useFilterPanelStore.getState().togglePanel()
    expect(useFilterPanelStore.getState().panelState).toBe('open')
  })

  it('closePanel transitions open to closing', () => {
    useFilterPanelStore.setState({ panelState: 'open' })
    useFilterPanelStore.getState().closePanel()
    expect(useFilterPanelStore.getState().panelState).toBe('closing')
  })

  it('closePanel is a no-op when already closed', () => {
    useFilterPanelStore.getState().closePanel()
    expect(useFilterPanelStore.getState().panelState).toBe('closed')
  })

  it('onAnimationEnd transitions closing to closed', () => {
    useFilterPanelStore.setState({ panelState: 'closing' })
    useFilterPanelStore.getState().onAnimationEnd()
    expect(useFilterPanelStore.getState().panelState).toBe('closed')
  })

  it('onAnimationEnd is a no-op when open', () => {
    useFilterPanelStore.setState({ panelState: 'open' })
    useFilterPanelStore.getState().onAnimationEnd()
    expect(useFilterPanelStore.getState().panelState).toBe('open')
  })

  it('setActiveFilterCount updates count', () => {
    useFilterPanelStore.getState().setActiveFilterCount(3)
    expect(useFilterPanelStore.getState().activeFilterCount).toBe(3)
  })
})
