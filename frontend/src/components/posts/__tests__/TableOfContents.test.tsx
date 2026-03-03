import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import TableOfContents from '../TableOfContents'

let mockActiveId: string | null = null

vi.mock('@/hooks/useActiveHeading', () => ({
  useActiveHeading: () => mockActiveId,
}))

function makeContentRef(...headings: Array<{ tag: string; id: string; text: string }>) {
  const div = document.createElement('div')
  for (const h of headings) {
    const el = document.createElement(h.tag)
    el.id = h.id
    el.textContent = h.text
    div.appendChild(el)
  }
  return { current: div }
}

beforeEach(() => {
  mockActiveId = null
})

function getTocPanel() {
  return document.querySelector('div[aria-hidden]')
}

function expectPanelOpen() {
  const panel = getTocPanel()
  expect(panel).not.toBeNull()
  expect(panel!.getAttribute('aria-hidden')).toBe('false')
}

function expectPanelClosed() {
  const panel = getTocPanel()
  expect(panel).not.toBeNull()
  expect(panel!.getAttribute('aria-hidden')).toBe('true')
  expect(panel!.className).toContain('pointer-events-none')
}

describe('TableOfContents', () => {
  it('renders nothing when fewer than 3 headings', () => {
    const ref = makeContentRef(
      { tag: 'h2', id: 'a', text: 'A' },
      { tag: 'h2', id: 'b', text: 'B' },
    )
    const { container } = render(<TableOfContents contentRef={ref} />)
    expect(container.innerHTML).toBe('')
  })

  it('renders toggle button when 3+ headings', () => {
    const ref = makeContentRef(
      { tag: 'h2', id: 'a', text: 'Section A' },
      { tag: 'h2', id: 'b', text: 'Section B' },
      { tag: 'h2', id: 'c', text: 'Section C' },
    )
    render(<TableOfContents contentRef={ref} />)
    expect(screen.getByRole('button', { name: /table of contents/i })).toBeInTheDocument()
  })

  it('shows TOC panel on button click', async () => {
    const ref = makeContentRef(
      { tag: 'h2', id: 'a', text: 'Section A' },
      { tag: 'h2', id: 'b', text: 'Section B' },
      { tag: 'h3', id: 'b1', text: 'Subsection B1' },
    )
    render(<TableOfContents contentRef={ref} />)

    await userEvent.click(screen.getByRole('button', { name: /table of contents/i }))

    expectPanelOpen()
    expect(screen.getByText('Section A')).toBeInTheDocument()
    expect(screen.getByText('Section B')).toBeInTheDocument()
    expect(screen.getByText('Subsection B1')).toBeInTheDocument()
  })

  it('closes panel on Escape key', async () => {
    const ref = makeContentRef(
      { tag: 'h2', id: 'a', text: 'Section A' },
      { tag: 'h2', id: 'b', text: 'Section B' },
      { tag: 'h2', id: 'c', text: 'Section C' },
    )
    render(<TableOfContents contentRef={ref} />)

    await userEvent.click(screen.getByRole('button', { name: /table of contents/i }))
    expectPanelOpen()

    await userEvent.keyboard('{Escape}')
    await waitFor(() => {
      expectPanelClosed()
    })
  })

  it('closes panel on click outside', async () => {
    const ref = makeContentRef(
      { tag: 'h2', id: 'a', text: 'Section A' },
      { tag: 'h2', id: 'b', text: 'Section B' },
      { tag: 'h2', id: 'c', text: 'Section C' },
    )
    render(<TableOfContents contentRef={ref} />)

    await userEvent.click(screen.getByRole('button', { name: /table of contents/i }))
    expectPanelOpen()

    await userEvent.click(document.body)
    await waitFor(() => {
      expectPanelClosed()
    })
  })

  it('closes panel when a TOC link is clicked', async () => {
    const ref = makeContentRef(
      { tag: 'h2', id: 'a', text: 'Section A' },
      { tag: 'h2', id: 'b', text: 'Section B' },
      { tag: 'h2', id: 'c', text: 'Section C' },
    )
    render(<TableOfContents contentRef={ref} />)

    await userEvent.click(screen.getByRole('button', { name: /table of contents/i }))
    await userEvent.click(screen.getByText('Section A'))
    await waitFor(() => {
      expectPanelClosed()
    })
  })

  it('highlights the active heading', async () => {
    mockActiveId = 'b'
    const ref = makeContentRef(
      { tag: 'h2', id: 'a', text: 'Section A' },
      { tag: 'h2', id: 'b', text: 'Section B' },
      { tag: 'h2', id: 'c', text: 'Section C' },
    )
    render(<TableOfContents contentRef={ref} />)

    await userEvent.click(screen.getByRole('button', { name: /table of contents/i }))

    const activeButton = screen.getByText('Section B')
    expect(activeButton.className).toContain('text-accent')
    expect(activeButton.className).toContain('font-medium')

    const inactiveButton = screen.getByText('Section A')
    expect(inactiveButton.className).toContain('text-muted')
    expect(inactiveButton.className).not.toContain('text-accent')
  })

  it('renders sidebar variant with "On this page" heading', () => {
    const ref = makeContentRef(
      { tag: 'h2', id: 'a', text: 'Section A' },
      { tag: 'h2', id: 'b', text: 'Section B' },
      { tag: 'h2', id: 'c', text: 'Section C' },
    )
    render(<TableOfContents contentRef={ref} variant="sidebar" />)

    expect(screen.getByText('On this page')).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: /table of contents/i })).toBeInTheDocument()
    expect(screen.getByText('Section A')).toBeInTheDocument()
    expect(screen.getByText('Section B')).toBeInTheDocument()
    expect(screen.getByText('Section C')).toBeInTheDocument()
  })

  it('indents h3 entries', async () => {
    const ref = makeContentRef(
      { tag: 'h2', id: 'a', text: 'Section A' },
      { tag: 'h3', id: 'a1', text: 'Sub A1' },
      { tag: 'h2', id: 'b', text: 'Section B' },
    )
    render(<TableOfContents contentRef={ref} />)

    await userEvent.click(screen.getByRole('button', { name: /table of contents/i }))

    const subItem = screen.getByText('Sub A1').closest('li')
    expect(subItem?.className).toContain('pl-')
  })
})
