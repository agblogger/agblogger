import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import { searchPosts } from '@/api/posts'
import type { SearchResult } from '@/api/client'

vi.mock('@/api/posts', () => ({
  searchPosts: vi.fn(),
}))

vi.mock('@/hooks/useKatex', () => ({
  useRenderedHtml: (html: string | null | undefined) =>
    html ? html.replace(/(<span class="math[^"]*">)(.*?)(<\/span>)/g, '$1[RENDERED]$3') : '',
}))

import SearchPage from '../SearchPage'

const mockSearchPosts = vi.mocked(searchPosts)

function renderSearch(query = '') {
  const path = query ? `/search?q=${encodeURIComponent(query)}` : '/search'
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/search" element={<SearchPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

const mockResults: SearchResult[] = [
  { id: 1, file_path: 'posts/hello.md', title: 'Hello World', rendered_excerpt: '<p>A first post</p>', created_at: '2026-02-01 12:00:00+00:00', rank: 1.0 },
  { id: 2, file_path: 'posts/react.md', title: 'React Guide', rendered_excerpt: '<p>Learn React</p>', created_at: '2026-02-02 12:00:00+00:00', rank: 0.9 },
]

describe('SearchPage', () => {
  beforeEach(() => {
    mockSearchPosts.mockReset()
  })

  it('no query shows placeholder', () => {
    renderSearch()
    expect(screen.getByText('Enter a search query above.')).toBeInTheDocument()
    expect(mockSearchPosts).not.toHaveBeenCalled()
  })

  it('empty query string does not fetch', () => {
    renderSearch('')
    expect(mockSearchPosts).not.toHaveBeenCalled()
  })

  it('displays results', async () => {
    mockSearchPosts.mockResolvedValue(mockResults)
    renderSearch('react')

    await waitFor(() => {
      expect(screen.getByText('Hello World')).toBeInTheDocument()
    })
    expect(screen.getByText('React Guide')).toBeInTheDocument()
    const links = screen.getAllByRole('link')
    expect(links.some((l) => l.getAttribute('href') === '/post/hello')).toBe(true)
  })

  it('shows no results message', async () => {
    mockSearchPosts.mockResolvedValue([])
    renderSearch('nonexistent')

    await waitFor(() => {
      expect(screen.getByText(/No results found for/)).toBeInTheDocument()
    })
    expect(screen.getByText(/Try different keywords/)).toBeInTheDocument()
  })

  it('shows error message on failure', async () => {
    mockSearchPosts.mockRejectedValue(new Error('Server error'))
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    renderSearch('failing')

    await waitFor(() => {
      expect(screen.getByText('Search failed. Please try again.')).toBeInTheDocument()
    })
    consoleSpy.mockRestore()
  })

  it('logs error to console on failure', async () => {
    const error = new Error('Server error')
    mockSearchPosts.mockRejectedValue(error)
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    renderSearch('failing')

    await waitFor(() => {
      expect(consoleSpy).toHaveBeenCalledWith('Search failed:', error)
    })
    consoleSpy.mockRestore()
  })

  it('shows search input with current query', async () => {
    mockSearchPosts.mockResolvedValue([])
    renderSearch('react')

    await waitFor(() => {
      expect(screen.getByPlaceholderText('Search posts...')).toHaveValue('react')
    })
  })

  it('shows search input when no query', () => {
    renderSearch()

    const input = screen.getByPlaceholderText('Search posts...')
    expect(input).toHaveValue('')
  })

  it('submit button is disabled when input is empty', () => {
    renderSearch()

    const button = screen.getByRole('button', { name: 'Search' })
    expect(button).toBeDisabled()
  })

  it('allows refining search via input', async () => {
    mockSearchPosts.mockResolvedValue([])
    renderSearch('react')

    await waitFor(() => {
      expect(screen.getByPlaceholderText('Search posts...')).toHaveValue('react')
    })

    const input = screen.getByPlaceholderText('Search posts...')
    await userEvent.clear(input)
    await userEvent.type(input, 'vue')
    expect(input).toHaveValue('vue')
  })

  it('renders KaTeX math in search result excerpts', async () => {
    const mathResult: SearchResult[] = [
      {
        id: 1,
        file_path: 'posts/math.md',
        title: 'Math Post',
        rendered_excerpt: '<p>Inline math: <span class="math inline">E = mc^2</span></p>',
        created_at: '2026-02-01 12:00:00+00:00',
        rank: 1.0,
      },
    ]
    mockSearchPosts.mockResolvedValue(mathResult)
    renderSearch('math')

    await waitFor(() => {
      expect(screen.getByText('Math Post')).toBeInTheDocument()
    })
    const excerptEl = screen.getByText('Math Post').closest('a')!.querySelector('.prose-excerpt')!
    expect(excerptEl.innerHTML).toContain('[RENDERED]')
  })

  it('formats dates in human-readable format', async () => {
    mockSearchPosts.mockResolvedValue(mockResults)
    renderSearch('react')

    await waitFor(() => {
      expect(screen.getByText('Feb 1, 2026')).toBeInTheDocument()
    })
    expect(screen.getByText('Feb 2, 2026')).toBeInTheDocument()
  })

  it('shows result count', async () => {
    mockSearchPosts.mockResolvedValue(mockResults)
    renderSearch('react')

    await waitFor(() => {
      expect(screen.getByText(/2 results for/)).toBeInTheDocument()
    })
  })
})
