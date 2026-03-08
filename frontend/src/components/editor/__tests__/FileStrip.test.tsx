import { createElement } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import type { AssetInfo } from '@/api/client'
import { fetchPostAssets, deletePostAsset } from '@/api/posts'
import FileStrip from '../FileStrip'

vi.mock('@/api/posts', () => ({
  fetchPostAssets: vi.fn(),
  deletePostAsset: vi.fn(),
  renamePostAsset: vi.fn(),
  uploadAssets: vi.fn(),
}))

vi.mock('@/api/client', async () => {
  const actual = await vi.importActual('@/api/client')
  return { ...actual }
})

const mockFetchPostAssets = vi.mocked(fetchPostAssets)
const mockDeletePostAsset = vi.mocked(deletePostAsset)

const sampleAssets: AssetInfo[] = [
  { name: 'photo.png', size: 1024, is_image: true },
  { name: 'data.csv', size: 2048, is_image: false },
]

interface StripProps {
  filePath: string | null
  body: string
  onBodyChange: (body: string) => void
  onInsertAtCursor: (text: string) => void
  disabled: boolean
}

function renderStrip(overrides: Partial<StripProps> = {}) {
  const props: StripProps = {
    filePath: 'posts/2026-03-08-test/index.md',
    body: 'Some markdown content',
    onBodyChange: vi.fn(),
    onInsertAtCursor: vi.fn(),
    disabled: false,
    ...overrides,
  }
  const result = render(createElement(FileStrip, props))
  return { ...result, ...props }
}

describe('FileStrip', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it('shows "save to start" message when post is unsaved', () => {
    renderStrip({ filePath: null })
    expect(screen.getByText('Save to start adding files')).toBeInTheDocument()
  })

  it('fetches and displays assets for saved post', async () => {
    mockFetchPostAssets.mockResolvedValue({ assets: sampleAssets })
    const user = userEvent.setup()

    renderStrip()

    // Expand the strip
    await user.click(screen.getByText(/Files/))

    await waitFor(() => {
      expect(screen.getByText('photo.png')).toBeInTheDocument()
      expect(screen.getByText('data.csv')).toBeInTheDocument()
    })
  })

  it('shows file count in collapsed header', async () => {
    mockFetchPostAssets.mockResolvedValue({
      assets: [{ name: 'photo.png', size: 1024, is_image: true }],
    })

    renderStrip()

    await waitFor(() => {
      expect(screen.getByText('Files (1)')).toBeInTheDocument()
    })
  })

  it('shows "Files" with no count when empty', async () => {
    mockFetchPostAssets.mockResolvedValue({ assets: [] })

    renderStrip()

    await waitFor(() => {
      expect(screen.getByText('Files')).toBeInTheDocument()
    })
  })

  it('shows delete confirmation when file is referenced in body', async () => {
    mockFetchPostAssets.mockResolvedValue({
      assets: [{ name: 'photo.png', size: 1024, is_image: true }],
    })
    const user = userEvent.setup()

    renderStrip({ body: 'Here is ![photo](photo.png) in my post' })

    // Expand the strip
    await user.click(screen.getByText(/Files/))

    await waitFor(() => {
      expect(screen.getByText('photo.png')).toBeInTheDocument()
    })

    // Open kebab menu and click Delete
    await user.click(screen.getByLabelText('menu'))
    await user.click(screen.getByText('Delete'))

    // Confirmation banner should appear
    expect(
      screen.getByText('This file is referenced in your post. Delete anyway?'),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Delete' })).toBeInTheDocument()
  })

  it('deletes without confirmation when file is not referenced', async () => {
    mockFetchPostAssets.mockResolvedValue({
      assets: [{ name: 'photo.png', size: 1024, is_image: true }],
    })
    mockDeletePostAsset.mockResolvedValue(undefined)
    const user = userEvent.setup()

    renderStrip({ body: 'No references here' })

    // Expand the strip
    await user.click(screen.getByText(/Files/))

    await waitFor(() => {
      expect(screen.getByText('photo.png')).toBeInTheDocument()
    })

    // Open kebab menu and click Delete
    await user.click(screen.getByLabelText('menu'))
    await user.click(screen.getByText('Delete'))

    // Should call deletePostAsset directly without confirmation
    await waitFor(() => {
      expect(mockDeletePostAsset).toHaveBeenCalledWith(
        'posts/2026-03-08-test/index.md',
        'photo.png',
      )
    })
  })
})
