import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import { useMarkdownPreview } from '@/hooks/useMarkdownPreview'
import MarkdownEditor from '../MarkdownEditor'

vi.mock('@/hooks/useMarkdownPreview', () => ({ useMarkdownPreview: vi.fn() }))

const mockPreview = vi.mocked(useMarkdownPreview)

beforeEach(() => {
  mockPreview.mockReturnValue({ html: '', error: false, hasContent: false })
})

describe('MarkdownEditor', () => {
  it('renders the textarea with the provided value and reports edits via onChange', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    render(<MarkdownEditor value="hello" onChange={onChange} />)
    const textarea = screen.getByRole('textbox')
    expect(textarea).toHaveValue('hello')
    await user.type(textarea, '!')
    expect(onChange).toHaveBeenCalled()
  })

  it('shows the empty-state placeholder when there is no content', () => {
    render(<MarkdownEditor value="" onChange={() => {}} />)
    expect(screen.getByText(/start typing to see a live preview/i)).toBeInTheDocument()
  })

  it('renders sanitized preview html when content exists', () => {
    mockPreview.mockReturnValue({ html: '<p>rendered</p>', error: false, hasContent: true })
    render(<MarkdownEditor value="x" onChange={() => {}} />)
    expect(screen.getByText('rendered')).toBeInTheDocument()
  })

  it('shows "Preview unavailable" when the preview errors', () => {
    mockPreview.mockReturnValue({ html: '', error: true, hasContent: true })
    render(<MarkdownEditor value="x" onChange={() => {}} />)
    expect(screen.getByText(/preview unavailable/i)).toBeInTheDocument()
  })

  it('calls onSave when the toolbar save button is clicked', async () => {
    const onSave = vi.fn()
    const user = userEvent.setup()
    render(<MarkdownEditor value="x" onChange={() => {}} onSave={onSave} canSave />)
    await user.click(screen.getByLabelText('Save'))
    expect(onSave).toHaveBeenCalledOnce()
  })

  it('saves on Cmd/Ctrl+S when canSave is true', async () => {
    const onSave = vi.fn()
    const user = userEvent.setup()
    render(<MarkdownEditor value="x" onChange={() => {}} onSave={onSave} canSave />)
    screen.getByRole('textbox').focus()
    await user.keyboard('{Control>}s{/Control}')
    expect(onSave).toHaveBeenCalledOnce()
  })

  it('does not save on Cmd/Ctrl+S when canSave is false', async () => {
    const onSave = vi.fn()
    const user = userEvent.setup()
    render(<MarkdownEditor value="" onChange={() => {}} onSave={onSave} canSave={false} />)
    screen.getByRole('textbox').focus()
    await user.keyboard('{Control>}s{/Control}')
    expect(onSave).not.toHaveBeenCalled()
  })

  it('applies a formatting shortcut (Ctrl+B) via onChange', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    render(<MarkdownEditor value="hi" onChange={onChange} />)
    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement
    textarea.focus()
    textarea.setSelectionRange(0, 2)
    await user.keyboard('{Control>}b{/Control}')
    expect(onChange).toHaveBeenCalledWith('**hi**')
  })

  it('renders the mobile edit/preview tab controls', () => {
    render(<MarkdownEditor value="" onChange={() => {}} />)
    expect(screen.getByRole('button', { name: 'Edit' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Preview' })).toBeInTheDocument()
  })

  it('does not render a save button when onSave is not provided', () => {
    render(<MarkdownEditor value="x" onChange={() => {}} />)
    expect(screen.queryByLabelText('Save')).not.toBeInTheDocument()
  })
})
