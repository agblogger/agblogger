import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi } from 'vitest'

vi.mock('@/hooks/useKatex', () => ({
  useRenderedHtml: (html: string | null) => html ?? '',
}))

import type { PostSummary } from '@/api/client'
import PostCard from '../PostCard'

function makePost(overrides: Partial<PostSummary> = {}): PostSummary {
  return {
    id: 1,
    file_path: 'posts/test.md',
    title: 'Test Post',
    author: 'Admin',
    created_at: '2026-02-01 12:00:00+00:00',
    modified_at: '2026-02-01 12:00:00+00:00',
    is_draft: false,
    rendered_excerpt: '<p>This is the excerpt.</p>',
    labels: [],
    ...overrides,
  }
}

function renderCard(post: PostSummary) {
  return render(
    <MemoryRouter>
      <PostCard post={post} />
    </MemoryRouter>,
  )
}

describe('PostCard', () => {
  it('renders title as link', () => {
    renderCard(makePost())
    const link = screen.getByRole('link')
    expect(link).toHaveAttribute('href', '/post/posts/test.md')
    expect(screen.getByText('Test Post')).toBeInTheDocument()
  })

  it('renders formatted date', () => {
    renderCard(makePost())
    expect(screen.getByText('Feb 1, 2026')).toBeInTheDocument()
  })

  it('renders author', () => {
    renderCard(makePost())
    expect(screen.getByText('Admin')).toBeInTheDocument()
  })

  it('hides author when null', () => {
    renderCard(makePost({ author: null }))
    expect(screen.queryByText('·')).not.toBeInTheDocument()
  })

  it('renders excerpt', () => {
    renderCard(makePost())
    expect(screen.getByText('This is the excerpt.')).toBeInTheDocument()
  })

  it('shows draft badge', () => {
    renderCard(makePost({ is_draft: true }))
    expect(screen.getByText('Draft')).toBeInTheDocument()
  })

  it('hides draft badge', () => {
    renderCard(makePost({ is_draft: false }))
    expect(screen.queryByText('Draft')).not.toBeInTheDocument()
  })

  it('renders label chips', () => {
    renderCard(makePost({ labels: ['swe', 'cs'] }))
    expect(screen.getByText('#swe')).toBeInTheDocument()
    expect(screen.getByText('#cs')).toBeInTheDocument()
  })

  it('handles malformed date', () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    renderCard(makePost({ created_at: 'not-a-date' }))
    // Falls back to the part before space, which is 'not-a-date'
    expect(screen.getByText('not-a-date')).toBeInTheDocument()
  })

  it('sanitizes script tags from rendered excerpt', () => {
    renderCard(makePost({ rendered_excerpt: '<p>Safe</p><script>alert("xss")</script>' }))
    expect(screen.getByText('Safe')).toBeInTheDocument()
    const excerptEl = screen.getByText('Safe').closest('div')
    expect(excerptEl?.innerHTML).not.toContain('<script>')
  })

  it('sanitizes event handler attributes from rendered excerpt', () => {
    renderCard(makePost({ rendered_excerpt: '<p>Text</p><img onerror="alert(1)" src="x">' }))
    expect(screen.getByText('Text')).toBeInTheDocument()
    const excerptEl = screen.getByText('Text').closest('div')
    expect(excerptEl?.innerHTML).not.toContain('onerror')
  })

  it('is wrapped in React.memo', async () => {
    const { default: PostCardModule } = await import('../PostCard')
    expect((PostCardModule as unknown as { $$typeof: symbol }).$$typeof).toBe(Symbol.for('react.memo'))
  })
})
