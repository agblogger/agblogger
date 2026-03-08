import { createElement } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'

import type { AssetInfo } from '@/api/client'
import FileCard from '../FileCard'

const imageAsset: AssetInfo = { name: 'photo.png', size: 1024, is_image: true }
const fileAsset: AssetInfo = { name: 'data.csv', size: 2048, is_image: false }
const filePath = 'posts/2026-03-08-test/index.md'

function renderCard(overrides: Partial<Parameters<typeof FileCard>[0]> = {}) {
  const props = {
    asset: imageAsset,
    filePath,
    onInsert: vi.fn(),
    onDelete: vi.fn(),
    onRename: vi.fn(),
    disabled: false,
    ...overrides,
  }
  const result = render(createElement(FileCard, props))
  return { ...result, ...props }
}

describe('FileCard', () => {
  it('renders filename', () => {
    renderCard()
    expect(screen.getByText('photo.png')).toBeInTheDocument()
  })

  it('renders image thumbnail for image assets', () => {
    renderCard({ asset: imageAsset })
    const img = screen.getByRole('img')
    expect(img).toBeInTheDocument()
    expect(img).toHaveAttribute('src', '/api/content/posts/2026-03-08-test/photo.png')
  })

  it('renders file icon for non-image assets', () => {
    renderCard({ asset: fileAsset })
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
  })

  it('shows menu on kebab click', async () => {
    const user = userEvent.setup()
    renderCard()

    await user.click(screen.getByLabelText('menu'))

    expect(screen.getByText('Insert')).toBeInTheDocument()
    expect(screen.getByText('Copy name')).toBeInTheDocument()
    expect(screen.getByText('Rename')).toBeInTheDocument()
    expect(screen.getByText('Delete')).toBeInTheDocument()
  })

  it('calls onInsert when Insert is clicked', async () => {
    const user = userEvent.setup()
    const { onInsert } = renderCard({ asset: imageAsset })

    await user.click(screen.getByLabelText('menu'))
    await user.click(screen.getByText('Insert'))

    expect(onInsert).toHaveBeenCalledWith('photo.png', true)
  })

  it('calls onDelete when Delete is clicked', async () => {
    const user = userEvent.setup()
    const { onDelete } = renderCard()

    await user.click(screen.getByLabelText('menu'))
    await user.click(screen.getByText('Delete'))

    expect(onDelete).toHaveBeenCalledWith('photo.png')
  })

  it('enters rename mode and confirms with Enter', async () => {
    const user = userEvent.setup()
    const { onRename } = renderCard()

    await user.click(screen.getByLabelText('menu'))
    await user.click(screen.getByText('Rename'))

    const input = screen.getByRole('textbox')
    await user.clear(input)
    await user.type(input, 'newname.png')
    await user.keyboard('{Enter}')

    expect(onRename).toHaveBeenCalledWith('photo.png', 'newname.png')
  })

  it('does not produce unhandled rejection when clipboard.writeText fails', async () => {
    const user = userEvent.setup()
    const originalClipboard = navigator.clipboard
    const unhandledRejections: PromiseRejectionEvent[] = []
    const handler = (e: PromiseRejectionEvent) => { unhandledRejections.push(e) }
    window.addEventListener('unhandledrejection', handler)

    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: vi.fn().mockRejectedValue(new Error('clipboard unavailable')) },
      writable: true,
      configurable: true,
    })

    renderCard({ disabled: false })

    await user.click(screen.getByLabelText('menu'))
    await user.click(screen.getByText('Copy name'))

    // Allow microtasks to settle
    await new Promise((r) => setTimeout(r, 50))

    // Menu should close even when clipboard fails
    expect(screen.queryByText('Copy name')).not.toBeInTheDocument()
    expect(unhandledRejections).toHaveLength(0)

    window.removeEventListener('unhandledrejection', handler)
    Object.defineProperty(navigator, 'clipboard', {
      value: originalClipboard,
      writable: true,
      configurable: true,
    })
  })

  it('cancels rename with Escape', async () => {
    const user = userEvent.setup()
    const { onRename } = renderCard()

    await user.click(screen.getByLabelText('menu'))
    await user.click(screen.getByText('Rename'))

    const input = screen.getByRole('textbox')
    await user.clear(input)
    await user.type(input, 'newname.png')
    await user.keyboard('{Escape}')

    expect(onRename).not.toHaveBeenCalled()
  })
})
