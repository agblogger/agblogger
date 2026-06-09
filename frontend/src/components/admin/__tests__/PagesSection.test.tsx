import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import { updateAdminPage } from '@/api/admin'
import type { AdminPageConfig } from '@/api/client'
import PagesSection from '../PagesSection'

vi.mock('@/api/admin', () => ({
  createAdminPage: vi.fn(),
  updateAdminPage: vi.fn().mockResolvedValue(undefined),
  updateAdminPageOrder: vi.fn(),
  deleteAdminPage: vi.fn(),
}))
vi.mock('@/stores/siteStore', () => ({ refreshSiteConfig: vi.fn() }))
vi.mock('@/hooks/useMarkdownPreview', () => ({
  useMarkdownPreview: () => ({ html: '', error: false, hasContent: false }),
}))

const mockUpdateAdminPage = vi.mocked(updateAdminPage)

const pages: AdminPageConfig[] = [
  { id: 'about', title: 'About', file: 'about.md', is_builtin: false, content: '# About' },
]

function renderSection() {
  return render(
    <PagesSection
      initialPages={pages}
      busy={false}
      onSaving={() => {}}
      onPagesChange={() => {}}
      onDirtyChange={() => {}}
    />,
  )
}

beforeEach(() => {
  mockUpdateAdminPage.mockClear()
})

describe('PagesSection editor integration', () => {
  it('edits page content through the shared MarkdownEditor and saves via its toolbar', async () => {
    const user = userEvent.setup()
    renderSection()

    await user.click(screen.getByText('About'))

    // The content editor is a textarea holding the page markdown.
    const textboxes = screen.getAllByRole('textbox')
    const contentArea = textboxes.find(
      (el): el is HTMLTextAreaElement => el.tagName === 'TEXTAREA',
    )
    expect(contentArea).toBeDefined()
    expect(contentArea).toHaveValue('# About')

    await user.clear(contentArea!)
    await user.type(contentArea!, '# Updated')
    await user.click(screen.getByLabelText('Save'))

    await waitFor(() =>
      expect(mockUpdateAdminPage).toHaveBeenCalledWith('about', { content: '# Updated' }),
    )
  })
})
