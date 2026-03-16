import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi } from 'vitest'
import SearchDropdown from '../SearchDropdown'
import type { SearchResult } from '@/api/client'

const results: SearchResult[] = [
  { id: 1, file_path: 'posts/hello.md', title: 'Hello World', rendered_excerpt: null, created_at: '2026-02-01 12:00:00+00:00', rank: 1.0 },
  { id: 2, file_path: 'posts/react.md', title: 'React Guide', rendered_excerpt: null, created_at: '2026-02-02 12:00:00+00:00', rank: 0.9 },
]

function renderDropdown(props: Partial<React.ComponentProps<typeof SearchDropdown>> = {}) {
  const defaults = {
    results,
    query: 'hello',
    highlightIndex: -1,
    onSelect: vi.fn(),
    onFooterClick: vi.fn(),
  }
  return render(
    <MemoryRouter>
      <SearchDropdown {...defaults} {...props} />
    </MemoryRouter>,
  )
}

describe('SearchDropdown', () => {
  it('renders result titles', () => {
    renderDropdown()
    expect(screen.getByText('Hello World')).toBeInTheDocument()
    expect(screen.getByText('React Guide')).toBeInTheDocument()
  })

  it('renders "View all results" footer when results exist', () => {
    renderDropdown()
    expect(screen.getByText('View all results')).toBeInTheDocument()
  })

  it('renders "No results found" with no footer when empty', () => {
    renderDropdown({ results: [] })
    expect(screen.getByText('No results found')).toBeInTheDocument()
    expect(screen.queryByText('View all results')).not.toBeInTheDocument()
  })

  it('highlights the item at highlightIndex', () => {
    renderDropdown({ highlightIndex: 0 })
    const options = screen.getAllByRole('option')
    expect(options[0]).toHaveAttribute('aria-selected', 'true')
    expect(options[1]).toHaveAttribute('aria-selected', 'false')
  })

  it('calls onSelect with file_path on mousedown', () => {
    const onSelect = vi.fn()
    renderDropdown({ onSelect })
    const option = screen.getAllByRole('option')[0]!
    // Use fireEvent for mousedown (userEvent doesn't have mousedown)
    option.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
    expect(onSelect).toHaveBeenCalledWith('posts/hello.md')
  })

  it('calls onFooterClick on footer mousedown', () => {
    const onFooterClick = vi.fn()
    renderDropdown({ onFooterClick })
    const footer = screen.getByText('View all results')
    footer.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
    expect(onFooterClick).toHaveBeenCalled()
  })

  it('uses role=listbox with correct ARIA attributes', () => {
    renderDropdown()
    expect(screen.getByRole('listbox')).toBeInTheDocument()
    const options = screen.getAllByRole('option')
    expect(options).toHaveLength(2)
    expect(options[0]).toHaveAttribute('id', 'search-result-0')
    expect(options[1]).toHaveAttribute('id', 'search-result-1')
  })

  it('renders dates for results', () => {
    renderDropdown()
    expect(screen.getByText('Feb 1, 2026')).toBeInTheDocument()
  })
})
