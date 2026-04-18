import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { SWRConfig } from 'swr'

import type { LabelResponse } from '@/api/client'
import { useAuthStore } from '@/stores/authStore'
import FilterPanel, { EMPTY_FILTER, type FilterState } from '../FilterPanel'

let mockPanelState: 'closed' | 'open' | 'closing' = 'closed'
const mockClosePanel = vi.fn()
const mockOnAnimationEnd = vi.fn()
const mockSetActiveFilterCount = vi.fn()

vi.mock('@/stores/filterPanelStore', () => ({
  useFilterPanelStore: (selector: (s: {
    panelState: string
    closePanel: () => void
    onAnimationEnd: () => void
    setActiveFilterCount: (n: number) => void
  }) => unknown) =>
    selector({
      panelState: mockPanelState,
      closePanel: mockClosePanel,
      onAnimationEnd: mockOnAnimationEnd,
      setActiveFilterCount: mockSetActiveFilterCount,
    }),
}))

const mockFetchLabels = vi.fn()

vi.mock('@/api/labels', () => ({
  fetchLabels: (...args: unknown[]) => mockFetchLabels(...args) as unknown,
}))

const allLabels: LabelResponse[] = [
  { id: 'swe', names: ['software engineering'], is_implicit: false, parents: [], children: [], post_count: 5 },
  { id: 'cs', names: ['computer science'], is_implicit: false, parents: [], children: ['swe'], post_count: 10 },
  { id: 'math', names: ['mathematics'], is_implicit: false, parents: [], children: [], post_count: 3 },
]

async function renderPanel(value: FilterState = EMPTY_FILTER, onChange = vi.fn()) {
  const result = render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <FilterPanel value={value} onChange={onChange} />
    </SWRConfig>,
  )
  // Flush microtasks from the initial fetchLabels() effect
  await act(async () => {})
  return { ...result, onChange }
}

describe('FilterPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockFetchLabels.mockResolvedValue(allLabels)
    mockPanelState = 'closed'
    useAuthStore.setState({
      user: null,
      isLoading: false,
      isLoggingOut: false,
      isInitialized: true,
      error: null,
    })
  })

  it('does not render a toggle button', async () => {
    await renderPanel()
    expect(screen.queryByText('Filters')).not.toBeInTheDocument()
  })

  it('shows panel contents when panelState is open', async () => {
    mockPanelState = 'open'
    await renderPanel()

    await waitFor(() => {
      expect(screen.getByPlaceholderText('Search labels...')).toBeInTheDocument()
    })
  })

  it('shows filter chips when panel is closed', async () => {
    const filter: FilterState = { ...EMPTY_FILTER, labels: ['swe'] }
    await renderPanel(filter)

    // Chip area renders #swe; the hidden panel label list also renders it
    const sweElements = screen.getAllByText('#swe')
    expect(sweElements.length).toBeGreaterThanOrEqual(1)
  })

  it('shows date range chips', async () => {
    const filter: FilterState = { ...EMPTY_FILTER, fromDate: '2026-01-01', toDate: '2026-02-01' }
    await renderPanel(filter)

    expect(screen.getByText('2026-01-01 - 2026-02-01')).toBeInTheDocument()
  })

  it('filters labels by search', async () => {
    mockPanelState = 'open'
    const user = userEvent.setup()
    await renderPanel()

    await waitFor(() => {
      expect(screen.getByText('#swe')).toBeInTheDocument()
    })

    await user.type(screen.getByPlaceholderText('Search labels...'), 'math')

    // Only math should be visible
    expect(screen.getByText('#math')).toBeInTheDocument()
    expect(screen.queryByText('#swe')).not.toBeInTheDocument()
    expect(screen.queryByText('#cs')).not.toBeInTheDocument()
  })

  it('filters labels by name case-insensitively', async () => {
    mockPanelState = 'open'
    const user = userEvent.setup()
    await renderPanel()

    await waitFor(() => {
      expect(screen.getByText('#swe')).toBeInTheDocument()
    })

    await user.type(screen.getByPlaceholderText('Search labels...'), 'Software')

    expect(screen.getByText('#swe')).toBeInTheDocument()
    expect(screen.queryByText('#math')).not.toBeInTheDocument()
  })

  it('toggles label selection', async () => {
    mockPanelState = 'open'
    const onChange = vi.fn()
    const user = userEvent.setup()
    await renderPanel(EMPTY_FILTER, onChange)

    await waitFor(() => {
      expect(screen.getByText('#swe')).toBeInTheDocument()
    })

    await user.click(screen.getByText('#swe'))

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ labels: ['swe'] }))
  })

  it('removes label from filter', async () => {
    mockPanelState = 'open'
    const onChange = vi.fn()
    const user = userEvent.setup()
    const filter: FilterState = { ...EMPTY_FILTER, labels: ['swe'] }
    await renderPanel(filter, onChange)

    await waitFor(() => {
      expect(screen.getByText('#swe')).toBeInTheDocument()
    })

    await user.click(screen.getByText('#swe'))

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ labels: [] }))
  })

  it('toggles label mode OR/AND', async () => {
    mockPanelState = 'open'
    const onChange = vi.fn()
    const user = userEvent.setup()
    await renderPanel(EMPTY_FILTER, onChange)

    await waitFor(() => {
      expect(screen.getByText('AND')).toBeInTheDocument()
    })

    await user.click(screen.getByText('AND'))

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ labelMode: 'and' }))
  })

  it('clears all filters via chip area', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    const filter: FilterState = { labels: ['swe'], labelMode: 'and', includeSublabels: false, fromDate: '2026-01-01', toDate: '' }
    await renderPanel(filter, onChange)

    // Chips area has "Clear all" (panel is closed, so only 1 visible)
    const clearAllButtons = screen.getAllByText('Clear all')
    await user.click(clearAllButtons[0]!)

    expect(onChange).toHaveBeenCalledWith(EMPTY_FILTER)
  })

  it('shows "No matching labels" when search has no results', async () => {
    mockPanelState = 'open'
    const user = userEvent.setup()
    await renderPanel()

    await waitFor(() => {
      expect(screen.getByPlaceholderText('Search labels...')).toBeInTheDocument()
    })

    await user.type(screen.getByPlaceholderText('Search labels...'), 'nonexistent')

    expect(screen.getByText('No matching labels')).toBeInTheDocument()
  })

  it('closes panel via Close button', async () => {
    mockPanelState = 'open'
    const user = userEvent.setup()
    await renderPanel()

    await waitFor(() => {
      expect(screen.getByText('Close')).toBeInTheDocument()
    })

    await user.click(screen.getByText('Close'))

    expect(mockClosePanel).toHaveBeenCalled()
  })

  it('updates from date', async () => {
    mockPanelState = 'open'
    const onChange = vi.fn()
    const user = userEvent.setup()
    await renderPanel(EMPTY_FILTER, onChange)

    await waitFor(() => {
      const dateInputs = document.querySelectorAll('input[type="date"]')
      expect(dateInputs.length).toBe(2)
    })

    const fromInput = document.querySelectorAll('input[type="date"]')[0] as HTMLInputElement
    // Use fireEvent since userEvent doesn't handle date inputs well
    await user.clear(fromInput)
    await user.type(fromInput, '2026-01-01')

    expect(onChange).toHaveBeenCalled()
  })

  it('removes label chip when X is clicked', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    const filter: FilterState = { ...EMPTY_FILTER, labels: ['swe'] }
    await renderPanel(filter, onChange)

    // Chip area: find the chip span (bg-tag-bg), not the panel label button
    const sweElements = screen.getAllByText('#swe')
    const chipSpan = sweElements.find((el) => el.classList.contains('bg-tag-bg'))
    const chipButton = chipSpan?.querySelector('button')
    expect(chipButton).toBeTruthy()
    await user.click(chipButton!)

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ labels: [] }))
  })

  it('removes date range chip when X is clicked', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    const filter: FilterState = { ...EMPTY_FILTER, fromDate: '2026-01-01', toDate: '2026-02-01' }
    await renderPanel(filter, onChange)

    const dateChipButton = screen.getByText('2026-01-01 - 2026-02-01').parentElement?.querySelector('button')
    expect(dateChipButton).toBeTruthy()
    await user.click(dateChipButton!)

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ fromDate: '', toDate: '' }))
  })

  it('clears all filters from inside panel', async () => {
    mockPanelState = 'open'
    const onChange = vi.fn()
    const user = userEvent.setup()
    const filter: FilterState = { labels: ['swe'], labelMode: 'or', includeSublabels: false, fromDate: '', toDate: '' }
    await renderPanel(filter, onChange)

    await waitFor(() => {
      // There should be a "Clear all" inside the panel
      const clearButtons = screen.getAllByText('Clear all')
      expect(clearButtons.length).toBeGreaterThanOrEqual(1)
    })

    // Click the last "Clear all" (the one inside the panel)
    const clearButtons = screen.getAllByText('Clear all')
    await user.click(clearButtons[clearButtons.length - 1]!)

    expect(onChange).toHaveBeenCalledWith(EMPTY_FILTER)
  })

  it('shows error message when label fetch fails', async () => {
    mockPanelState = 'open'
    mockFetchLabels.mockRejectedValue(new Error('Network error'))
    vi.spyOn(console, 'error').mockImplementation(() => {})
    await renderPanel()

    await waitFor(() => {
      expect(screen.getByText('Failed to load labels')).toBeInTheDocument()
    })
    expect(screen.queryByText('No matching labels')).not.toBeInTheDocument()
  })

  it('toggles includeSublabels checkbox', async () => {
    mockPanelState = 'open'
    const onChange = vi.fn()
    const user = userEvent.setup()
    await renderPanel(EMPTY_FILTER, onChange)

    await waitFor(() => {
      expect(screen.getByLabelText('incl. sub-labels')).toBeInTheDocument()
    })

    await user.click(screen.getByLabelText('incl. sub-labels'))

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ includeSublabels: true }))
  })

  it('calls setActiveFilterCount with correct count', async () => {
    const filter: FilterState = { ...EMPTY_FILTER, labels: ['swe', 'cs'], fromDate: '2026-01-01' }
    await renderPanel(filter)

    expect(mockSetActiveFilterCount).toHaveBeenCalledWith(3)
  })
})
