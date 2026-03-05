import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import { fetchLabels } from '@/api/labels'
import type { LabelResponse, UserResponse } from '@/api/client'

vi.mock('@/api/labels', () => ({
  fetchLabels: vi.fn(),
}))

vi.mock('@/pages/LabelGraphPage', () => ({
  default: ({ viewToggle }: { viewToggle: React.ReactNode }) => (
    <div data-testid="graph-view">Graph View{viewToggle}</div>
  ),
}))

let mockUser: UserResponse | null = null

vi.mock('@/stores/authStore', () => ({
  useAuthStore: (selector: (s: { user: UserResponse | null }) => unknown) =>
    selector({ user: mockUser }),
}))

import LabelsPage from '../LabelsPage'

const mockFetchLabels = vi.mocked(fetchLabels)

const sampleLabels: LabelResponse[] = [
  {
    id: 'swe',
    names: ['software engineering'],
    is_implicit: false,
    parents: ['cs'],
    children: [],
    post_count: 5,
  },
  {
    id: 'math',
    names: ['mathematics'],
    is_implicit: false,
    parents: [],
    children: [],
    post_count: 3,
  },
]

function renderLabelsPage() {
  return render(
    <MemoryRouter initialEntries={['/labels']}>
      <LabelsPage />
    </MemoryRouter>,
  )
}

describe('LabelsPage', () => {
  beforeEach(() => {
    mockUser = null
    mockFetchLabels.mockReset()
  })

  it('renders labels in list view by default', async () => {
    mockFetchLabels.mockResolvedValue(sampleLabels)
    renderLabelsPage()

    await waitFor(() => {
      expect(screen.getByText('#swe')).toBeInTheDocument()
    })
    expect(screen.getByText('#math')).toBeInTheDocument()
    expect(screen.getByText('5 posts')).toBeInTheDocument()
    expect(screen.getByText('3 posts')).toBeInTheDocument()
  })

  it('switches to graph view when Graph button is clicked', async () => {
    mockFetchLabels.mockResolvedValue(sampleLabels)
    renderLabelsPage()

    await waitFor(() => {
      expect(screen.getByText('#swe')).toBeInTheDocument()
    })

    await userEvent.click(screen.getByRole('button', { name: 'Graph' }))
    expect(await screen.findByTestId('graph-view')).toBeInTheDocument()
    expect(screen.queryByText('#swe')).not.toBeInTheDocument()
  })

  it('switches back to list view when List button is clicked', async () => {
    mockFetchLabels.mockResolvedValue(sampleLabels)
    renderLabelsPage()

    await waitFor(() => {
      expect(screen.getByText('#swe')).toBeInTheDocument()
    })

    await userEvent.click(screen.getByRole('button', { name: 'Graph' }))
    expect(await screen.findByTestId('graph-view')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'List' }))
    await waitFor(() => {
      expect(screen.getByText('#swe')).toBeInTheDocument()
    })
    expect(screen.queryByTestId('graph-view')).not.toBeInTheDocument()
  })

  it('shows loading spinner initially', () => {
    mockFetchLabels.mockReturnValue(new Promise(() => {}))
    renderLabelsPage()

    expect(screen.getByRole('heading', { name: 'Labels' })).toBeInTheDocument()
    expect(screen.queryByText('#swe')).not.toBeInTheDocument()
  })

  it('shows error message on fetch failure', async () => {
    mockFetchLabels.mockRejectedValue(new Error('Network error'))
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    renderLabelsPage()

    await waitFor(() => {
      expect(screen.getByText('Failed to load labels. Please try again later.')).toBeInTheDocument()
    })
    consoleSpy.mockRestore()
  })

  it('shows empty state when no labels exist', async () => {
    mockFetchLabels.mockResolvedValue([])
    renderLabelsPage()

    await waitFor(() => {
      expect(screen.getByText('No labels defined yet.')).toBeInTheDocument()
    })
  })
})
