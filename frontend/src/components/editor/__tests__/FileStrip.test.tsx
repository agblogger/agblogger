import { createElement } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import type { AssetInfo } from '@/api/client'
import { HTTPError } from '@/api/client'
import { fetchPostAssets, deletePostAsset, renamePostAsset, uploadAssets } from '@/api/posts'
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
const mockRenamePostAsset = vi.mocked(renamePostAsset)
const httpErrorOptions = {} as ConstructorParameters<typeof HTTPError>[2]

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

  it('only rewrites markdown asset destinations when renaming', async () => {
    mockFetchPostAssets.mockResolvedValue({
      assets: [{ name: 'photo.png', size: 1024, is_image: true }],
    })
    mockRenamePostAsset.mockResolvedValue({ name: 'poster.png', size: 1024, is_image: true })
    const user = userEvent.setup()
    const onBodyChange = vi.fn()

    renderStrip({
      body: [
        'Plain photo.png text',
        '![cover](photo.png)',
        '[download](photo.png)',
        '`photo.png` in code',
        'my-photo.png',
      ].join('\n'),
      onBodyChange,
    })

    await user.click(screen.getByText(/Files/))

    await waitFor(() => {
      expect(screen.getByText('photo.png')).toBeInTheDocument()
    })

    await user.click(screen.getByLabelText('menu'))
    await user.click(screen.getByText('Rename'))

    const input = screen.getByRole('textbox')
    await user.clear(input)
    await user.type(input, 'poster.png')
    await user.tab()

    await waitFor(() => {
      expect(mockRenamePostAsset).toHaveBeenCalledWith(
        'posts/2026-03-08-test/index.md',
        'photo.png',
        'poster.png',
      )
    })
    expect(onBodyChange).toHaveBeenCalledWith(
      [
        'Plain photo.png text',
        '![cover](poster.png)',
        '[download](poster.png)',
        '`photo.png` in code',
        'my-photo.png',
      ].join('\n'),
    )
  })

  it('does not corrupt filenames that contain the renamed name as a substring', async () => {
    mockFetchPostAssets.mockResolvedValue({
      assets: [{ name: 'a.png', size: 512, is_image: true }],
    })
    mockRenamePostAsset.mockResolvedValue({ name: 'b.png', size: 512, is_image: true })
    const user = userEvent.setup()
    const onBodyChange = vi.fn()

    renderStrip({
      body: [
        '![alt](a.png)',
        '[text](a.png)',
        '![banana](banana.png)',
        'I ate a.png banana.png',
      ].join('\n'),
      onBodyChange,
    })

    await user.click(screen.getByText(/Files/))

    await waitFor(() => {
      expect(screen.getByText('a.png')).toBeInTheDocument()
    })

    await user.click(screen.getByLabelText('menu'))
    await user.click(screen.getByText('Rename'))

    const input = screen.getByRole('textbox')
    await user.clear(input)
    await user.type(input, 'b.png')
    await user.tab()

    await waitFor(() => {
      expect(mockRenamePostAsset).toHaveBeenCalledWith(
        'posts/2026-03-08-test/index.md',
        'a.png',
        'b.png',
      )
    })
    expect(onBodyChange).toHaveBeenCalledWith(
      [
        '![alt](b.png)',
        '[text](b.png)',
        '![banana](banana.png)',
        'I ate a.png banana.png',
      ].join('\n'),
    )
  })

  it('shows backend error detail instead of raw status code on rename failure', async () => {
    mockFetchPostAssets.mockResolvedValue({
      assets: [{ name: 'photo.png', size: 1024, is_image: true }],
    })
    const errorResponse = new Response(JSON.stringify({ detail: 'File already exists' }), {
      status: 409,
      statusText: 'Conflict',
    })
    mockRenamePostAsset.mockRejectedValue(
      new HTTPError(errorResponse, new Request('http://test'), httpErrorOptions),
    )
    const user = userEvent.setup()

    renderStrip()

    await user.click(screen.getByText(/Files/))

    await waitFor(() => {
      expect(screen.getByText('photo.png')).toBeInTheDocument()
    })

    await user.click(screen.getByLabelText('menu'))
    await user.click(screen.getByText('Rename'))

    const input = screen.getByRole('textbox')
    await user.clear(input)
    await user.type(input, 'other.png')
    await user.tab()

    await waitFor(() => {
      expect(screen.getByText('File already exists')).toBeInTheDocument()
    })
    // Ensure the raw status code is NOT shown
    expect(screen.queryByText(/409/)).not.toBeInTheDocument()
  })

  it('shows backend error detail instead of raw status code on delete failure', async () => {
    mockFetchPostAssets.mockResolvedValue({
      assets: [{ name: 'photo.png', size: 1024, is_image: true }],
    })
    const errorResponse = new Response(JSON.stringify({ detail: 'Asset is protected' }), {
      status: 403,
      statusText: 'Forbidden',
    })
    mockDeletePostAsset.mockRejectedValue(
      new HTTPError(errorResponse, new Request('http://test'), httpErrorOptions),
    )
    const user = userEvent.setup()

    renderStrip({ body: 'No references here' })

    await user.click(screen.getByText(/Files/))

    await waitFor(() => {
      expect(screen.getByText('photo.png')).toBeInTheDocument()
    })

    await user.click(screen.getByLabelText('menu'))
    await user.click(screen.getByText('Delete'))

    await waitFor(() => {
      expect(screen.getByText('Asset is protected')).toBeInTheDocument()
    })
    expect(screen.queryByText(/403/)).not.toBeInTheDocument()
  })

  it('shows backend error detail instead of raw status code on load failure', async () => {
    const errorResponse = new Response(JSON.stringify({ detail: 'Post not found' }), {
      status: 404,
      statusText: 'Not Found',
    })
    mockFetchPostAssets.mockRejectedValue(
      new HTTPError(errorResponse, new Request('http://test'), httpErrorOptions),
    )
    const user = userEvent.setup()

    renderStrip()

    await user.click(screen.getByText(/Files/))

    await waitFor(() => {
      expect(screen.getByText('Post not found')).toBeInTheDocument()
    })
    expect(screen.queryByText(/404/)).not.toBeInTheDocument()
  })

  it('shows backend error detail instead of raw status code on upload failure', async () => {
    mockFetchPostAssets.mockResolvedValue({ assets: [] })
    const errorResponse = new Response(JSON.stringify({ detail: 'File too large' }), {
      status: 413,
      statusText: 'Payload Too Large',
    })
    vi.mocked(uploadAssets).mockRejectedValue(
      new HTTPError(errorResponse, new Request('http://test'), httpErrorOptions),
    )
    const user = userEvent.setup()

    renderStrip()

    await user.click(screen.getByText(/Files/))

    await waitFor(() => {
      expect(screen.getByLabelText('Upload file')).toBeInTheDocument()
    })

    // Create a mock file and trigger upload
    const file = new File(['content'], 'big.png', { type: 'image/png' })
    const uploadInput = document.querySelector('input[type="file"]') as HTMLInputElement
    await user.upload(uploadInput, file)

    await waitFor(() => {
      expect(screen.getByText('File too large')).toBeInTheDocument()
    })
    expect(screen.queryByText(/413/)).not.toBeInTheDocument()
  })
})
