import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { SWRConfig } from 'swr'

import { fetchLabels } from '@/api/labels'
import type { LabelResponse, UserResponse } from '@/api/client'

vi.mock('@/api/labels', () => ({
  fetchLabels: vi.fn(),
}))

vi.mock('@/pages/LabelGraphPage', () => ({
  default: ({ search }: { search: string }) => (
    <div data-testid="graph-view">Graph View (search: {search})</div>
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
    id: 'cs',
    names: ['computer science'],
    is_implicit: false,
    parents: [],
    children: ['swe', 'math'],
    post_count: 10,
  },
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
    parents: ['cs'],
    children: [],
    post_count: 3,
  },
]

function renderLabelsPage() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <MemoryRouter initialEntries={['/labels']}>
        <LabelsPage />
      </MemoryRouter>
    </SWRConfig>,
  )
}

function getCardByLabel(labelId: string): HTMLElement {
  return screen.getByLabelText(`Open label #${labelId}`).closest('div[class*="group"]') as HTMLElement
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
      expect(within(getCardByLabel('swe')).getByText('#swe')).toBeInTheDocument()
    })
    expect(within(getCardByLabel('math')).getByText('#math')).toBeInTheDocument()
    expect(within(getCardByLabel('swe')).getByText('5 posts')).toBeInTheDocument()
    expect(within(getCardByLabel('math')).getByText('3 posts')).toBeInTheDocument()
  })

  it('switches to graph view when Graph button is clicked', async () => {
    mockFetchLabels.mockResolvedValue(sampleLabels)
    renderLabelsPage()

    await waitFor(() => {
      expect(screen.getByLabelText('Open label #swe')).toBeInTheDocument()
    })

    await userEvent.click(screen.getByRole('button', { name: 'Graph' }))
    expect(await screen.findByTestId('graph-view')).toBeInTheDocument()
    expect(screen.queryByText('#swe')).not.toBeInTheDocument()
  })

  it('switches back to list view when List button is clicked', async () => {
    mockFetchLabels.mockResolvedValue(sampleLabels)
    renderLabelsPage()

    await waitFor(() => {
      expect(screen.getByLabelText('Open label #swe')).toBeInTheDocument()
    })

    await userEvent.click(screen.getByRole('button', { name: 'Graph' }))
    expect(await screen.findByTestId('graph-view')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'List' }))
    await waitFor(() => {
      expect(screen.getByLabelText('Open label #swe')).toBeInTheDocument()
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

  it('filters labels by search input', async () => {
    mockFetchLabels.mockResolvedValue(sampleLabels)
    renderLabelsPage()

    await waitFor(() => {
      expect(screen.getByLabelText('Open label #swe')).toBeInTheDocument()
    })

    await userEvent.type(screen.getByPlaceholderText('Filter labels...'), 'math')

    expect(screen.queryByLabelText('Open label #swe')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Open label #math')).toBeInTheDocument()
  })

  it('shows empty message when search matches nothing', async () => {
    mockFetchLabels.mockResolvedValue(sampleLabels)
    renderLabelsPage()

    await waitFor(() => {
      expect(screen.getByLabelText('Open label #swe')).toBeInTheDocument()
    })

    await userEvent.type(screen.getByPlaceholderText('Filter labels...'), 'zzzzz')

    expect(screen.queryByText('#swe')).not.toBeInTheDocument()
    expect(screen.queryByText('#math')).not.toBeInTheDocument()
    expect(screen.getByText('No labels match your search.')).toBeInTheDocument()
  })

  it('shows all labels when search is cleared', async () => {
    mockFetchLabels.mockResolvedValue(sampleLabels)
    renderLabelsPage()

    await waitFor(() => {
      expect(screen.getByLabelText('Open label #swe')).toBeInTheDocument()
    })

    const searchInput = screen.getByPlaceholderText('Filter labels...')
    await userEvent.type(searchInput, 'math')
    expect(screen.queryByLabelText('Open label #swe')).not.toBeInTheDocument()

    await userEvent.clear(searchInput)
    expect(screen.getByLabelText('Open label #swe')).toBeInTheDocument()
    expect(screen.getByLabelText('Open label #math')).toBeInTheDocument()
  })

  it('filters labels by display name', async () => {
    mockFetchLabels.mockResolvedValue(sampleLabels)
    renderLabelsPage()

    await waitFor(() => {
      expect(screen.getByLabelText('Open label #swe')).toBeInTheDocument()
    })

    await userEvent.type(screen.getByPlaceholderText('Filter labels...'), 'software')

    expect(screen.getByLabelText('Open label #swe')).toBeInTheDocument()
    expect(screen.queryByLabelText('Open label #math')).not.toBeInTheDocument()
  })

  it('displays children as clickable chips', async () => {
    mockFetchLabels.mockResolvedValue(sampleLabels)
    renderLabelsPage()

    await waitFor(() => {
      expect(screen.getByLabelText('Open label #cs')).toBeInTheDocument()
    })

    const csCard = getCardByLabel('cs')
    const childLinks = csCard.querySelectorAll('a[href="/labels/swe"], a[href="/labels/math"]')
    expect(childLinks).toHaveLength(2)
  })

  it('does not show children chips when label has no children', async () => {
    mockFetchLabels.mockResolvedValue(sampleLabels)
    renderLabelsPage()

    await waitFor(() => {
      expect(screen.getByLabelText('Open label #math')).toBeInTheDocument()
    })

    // #math has no children — the only links should be the card overlay and possibly a parent link
    const mathCard = getCardByLabel('math')
    const allLinks = Array.from(mathCard.querySelectorAll('a'))
    const nonCardLinks = allLinks.filter(
      (a) => a.getAttribute('href') !== '/labels/math' && !a.getAttribute('href')?.includes('/settings'),
    )
    // Only the parent link (/labels/cs) expected, no child chip links
    expect(nonCardLinks).toHaveLength(1)
    expect(nonCardLinks[0]!.getAttribute('href')).toBe('/labels/cs')
  })

  it('displays parents as subtle clickable links', async () => {
    mockFetchLabels.mockResolvedValue(sampleLabels)
    renderLabelsPage()

    await waitFor(() => {
      expect(screen.getByLabelText('Open label #swe')).toBeInTheDocument()
    })

    // The #swe card should show "in" text with a link to parent #cs
    const sweCard = getCardByLabel('swe')
    expect(sweCard.textContent).toContain('in')
    const parentLink = sweCard.querySelector('a[href="/labels/cs"]')
    expect(parentLink).not.toBeNull()
    expect(parentLink!.textContent).toBe('#cs')
  })

  it('does not show parents section when label has no parents', async () => {
    mockFetchLabels.mockResolvedValue(sampleLabels)
    renderLabelsPage()

    await waitFor(() => {
      expect(screen.getByLabelText('Open label #cs')).toBeInTheDocument()
    })

    // The #cs card has no parents — should not show "in" text
    const csCard = getCardByLabel('cs')
    const inSpan = Array.from(csCard.querySelectorAll('span')).find(
      (el) => el.textContent.trim() === 'in',
    )
    expect(inSpan).toBeUndefined()
  })

  it('shows New Label button when user is authenticated', async () => {
    mockUser = { id: 1, username: 'admin', email: 'a@t.com', display_name: null, is_admin: true }
    mockFetchLabels.mockResolvedValue(sampleLabels)
    renderLabelsPage()
    expect(await screen.findByRole('link', { name: /new label/i })).toBeInTheDocument()
  })

  it('hides New Label button when user is authenticated but not an admin', async () => {
    mockUser = {
      id: 2,
      username: 'author',
      email: 'author@t.com',
      display_name: null,
      is_admin: false,
    }
    mockFetchLabels.mockResolvedValue(sampleLabels)
    renderLabelsPage()
    await screen.findByLabelText('Open label #cs')
    expect(screen.queryByRole('link', { name: /new label/i })).not.toBeInTheDocument()
  })

  it('shows Settings links when user is admin', async () => {
    mockUser = { id: 1, username: 'admin', email: 'a@t.com', display_name: null, is_admin: true }
    mockFetchLabels.mockResolvedValue(sampleLabels)
    renderLabelsPage()
    await screen.findByLabelText('Open label #cs')
    expect(screen.getByLabelText('Settings for cs')).toBeInTheDocument()
  })

  it('hides Settings links when user is not admin', async () => {
    mockUser = { id: 2, username: 'author', email: 'author@t.com', display_name: null, is_admin: false }
    mockFetchLabels.mockResolvedValue(sampleLabels)
    renderLabelsPage()
    await screen.findByLabelText('Open label #cs')
    expect(screen.queryByLabelText('Settings for cs')).not.toBeInTheDocument()
  })

  it('hides Settings links when user is not authenticated', async () => {
    mockUser = null
    mockFetchLabels.mockResolvedValue(sampleLabels)
    renderLabelsPage()
    await screen.findByLabelText('Open label #cs')
    expect(screen.queryByLabelText('Settings for cs')).not.toBeInTheDocument()
  })

  it('hides New Label button when user is not authenticated', async () => {
    mockUser = null
    mockFetchLabels.mockResolvedValue(sampleLabels)
    renderLabelsPage()
    await screen.findByLabelText('Open label #cs')
    expect(screen.queryByRole('link', { name: /new label/i })).not.toBeInTheDocument()
  })
})
