import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest'

import { useMarkdownPreview } from '@/hooks/useMarkdownPreview'
import MarkdownEditor from '../MarkdownEditor'

vi.mock('@/hooks/useMarkdownPreview', () => ({ useMarkdownPreview: vi.fn() }))
vi.mock('@/hooks/usePostAssets', () => ({
  usePostAssets: () => ({ data: { assets: [] }, error: undefined, mutate: vi.fn() }),
}))
vi.mock('@/api/posts', () => ({
  uploadAssets: vi.fn(),
  deletePostAsset: vi.fn(),
  renamePostAsset: vi.fn(),
}))

const mockPreview = vi.mocked(useMarkdownPreview)

beforeAll(() => {
  // JSDOM does not implement Range.getBoundingClientRect. Define a stub
  // (returning a zero rect) so vi.spyOn can mock it in individual tests that
  // simulate browser layout. The zero height acts as the "no layout" signal
  // that makes getVisualRowBounds fall back to logical-line behavior.
  if (!('getBoundingClientRect' in Range.prototype)) {
    Object.defineProperty(Range.prototype, 'getBoundingClientRect', {
      value: () =>
        ({ top: 0, height: 0, width: 0, left: 0, bottom: 0, right: 0, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect,
      writable: true,
      configurable: true,
    })
  }
})

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
    const textarea = screen.getByRole<HTMLTextAreaElement>('textbox')
    textarea.focus()
    textarea.setSelectionRange(0, 2)
    await user.keyboard('{Control>}b{/Control}')
    expect(onChange).toHaveBeenCalledWith('**hi**')
  })

  it('inserts two spaces on Tab and keeps focus in the textarea', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    render(<MarkdownEditor value="ab" onChange={onChange} />)
    const textarea = screen.getByRole<HTMLTextAreaElement>('textbox')
    textarea.focus()
    textarea.setSelectionRange(2, 2)
    await user.keyboard('{Tab}')
    expect(onChange).toHaveBeenCalledWith('ab  ')
    expect(textarea).toHaveFocus()
  })

  it('indents every line of a multi-line selection on Tab', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    render(<MarkdownEditor value={'one\ntwo'} onChange={onChange} />)
    const textarea = screen.getByRole<HTMLTextAreaElement>('textbox')
    textarea.focus()
    textarea.setSelectionRange(0, 7)
    await user.keyboard('{Tab}')
    expect(onChange).toHaveBeenCalledWith('  one\n  two')
  })

  it('dedents a multi-line selection on Shift+Tab', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    render(<MarkdownEditor value={'  one\n  two'} onChange={onChange} />)
    const textarea = screen.getByRole<HTMLTextAreaElement>('textbox')
    textarea.focus()
    textarea.setSelectionRange(0, 11)
    await user.keyboard('{Shift>}{Tab}{/Shift}')
    expect(onChange).toHaveBeenCalledWith('one\ntwo')
  })

  it('moves the caret with smart Home and End', async () => {
    const user = userEvent.setup()
    render(<MarkdownEditor value="  hello" onChange={() => {}} />)
    const textarea = screen.getByRole<HTMLTextAreaElement>('textbox')
    textarea.focus()
    textarea.setSelectionRange(7, 7)
    await user.keyboard('{Home}')
    expect(textarea.selectionStart).toBe(2) // first non-whitespace
    await user.keyboard('{Home}')
    expect(textarea.selectionStart).toBe(0) // toggles to column 0
    await user.keyboard('{End}')
    expect(textarea.selectionStart).toBe(7) // end of line
  })

  it('Home moves to the word-wrap visual row start, not a fixed-char-count offset', async () => {
    // "hello world" wraps visually after "hello " (word boundary at char 6).
    // With character-counting charsPerRow the current code picks the wrong row
    // start. The DOM-mirror fix must detect the actual word-wrap boundary.
    //
    // We stub Range.prototype.getBoundingClientRect to simulate the layout:
    //   chars 0-5 → top=0 (row 0)   chars 6-10 → top=20 (row 1)
    // Caret at 8 is on row 1, so Home must move to 6, not to 0.
    const user = userEvent.setup()
    render(<MarkdownEditor value="hello world" onChange={() => {}} />)
    const textarea = screen.getByRole<HTMLTextAreaElement>('textbox')

    Object.defineProperty(textarea, 'clientWidth', { value: 100, configurable: true })

    const spy = vi.spyOn(Range.prototype, 'getBoundingClientRect').mockImplementation(function (this: Range) {
      const top = this.startOffset < 6 ? 0 : 20
      return { top, height: 20, width: 8, left: 0, bottom: top + 20, right: 8, x: 0, y: top, toJSON: () => ({}) } as DOMRect
    })

    textarea.focus()
    textarea.setSelectionRange(8, 8) // within "world" on visual row 1
    await user.keyboard('{Home}')
    expect(textarea.selectionStart).toBe(6) // visual row 1 start = start of "world"

    spy.mockRestore()
  })

  it('End moves to the word-wrap visual row end, not a fixed-char-count offset', async () => {
    // Same layout: "hello " on row 0, "world" on row 1.
    // Caret at 3 is on row 0, so End must move to 6 (first char of next row).
    const user = userEvent.setup()
    render(<MarkdownEditor value="hello world" onChange={() => {}} />)
    const textarea = screen.getByRole<HTMLTextAreaElement>('textbox')

    Object.defineProperty(textarea, 'clientWidth', { value: 100, configurable: true })

    const spy = vi.spyOn(Range.prototype, 'getBoundingClientRect').mockImplementation(function (this: Range) {
      const top = this.startOffset < 6 ? 0 : 20
      return { top, height: 20, width: 8, left: 0, bottom: top + 20, right: 8, x: 0, y: top, toJSON: () => ({}) } as DOMRect
    })

    textarea.focus()
    textarea.setSelectionRange(3, 3) // within "hello" on visual row 0
    await user.keyboard('{End}')
    expect(textarea.selectionStart).toBe(6) // visual row 0 end = first char of row 1

    spy.mockRestore()
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

  it('toggles fullscreen via the toolbar and back again', async () => {
    const user = userEvent.setup()
    render(<MarkdownEditor value="x" onChange={() => {}} />)
    await user.click(screen.getByLabelText('Enter fullscreen'))
    expect(screen.getByLabelText('Exit fullscreen')).toBeInTheDocument()
    await user.click(screen.getByLabelText('Exit fullscreen'))
    expect(screen.getByLabelText('Enter fullscreen')).toBeInTheDocument()
  })

  it('exits fullscreen when Escape is pressed', async () => {
    const user = userEvent.setup()
    render(<MarkdownEditor value="x" onChange={() => {}} />)
    await user.click(screen.getByLabelText('Enter fullscreen'))
    expect(screen.getByLabelText('Exit fullscreen')).toBeInTheDocument()
    await user.keyboard('{Escape}')
    expect(screen.getByLabelText('Enter fullscreen')).toBeInTheDocument()
  })

  it('portals the editor out of its host container when fullscreen', async () => {
    // Hosts (EditorPage, AdminPage) wrap the editor in a transformed
    // `animate-fade-in` element, which establishes a containing block for the
    // `fixed inset-0` overlay. Portaling to document.body escapes it so
    // fullscreen covers the whole viewport, not just the host's column.
    const user = userEvent.setup()
    const { container } = render(<MarkdownEditor value="x" onChange={() => {}} />)
    expect(container.contains(screen.getByRole('textbox'))).toBe(true)

    await user.click(screen.getByLabelText('Enter fullscreen'))
    const fsTextarea = screen.getByRole('textbox')
    expect(container.contains(fsTextarea)).toBe(false)
    expect(document.body.contains(fsTextarea)).toBe(true)

    await user.click(screen.getByLabelText('Exit fullscreen'))
    expect(container.contains(screen.getByRole('textbox'))).toBe(true)
  })

  it('does not render asset UI when enableAssets is omitted', () => {
    render(<MarkdownEditor value="x" onChange={() => {}} />)
    expect(screen.queryByLabelText(/^Image/)).not.toBeInTheDocument()
    expect(screen.queryByText(/^Files/)).not.toBeInTheDocument()
  })

  it('renders the file strip and an image button when assets are enabled', () => {
    render(
      <MarkdownEditor
        value="x"
        onChange={() => {}}
        enableAssets
        filePath="posts/a/index.md"
      />,
    )
    expect(screen.getByText(/^Files/)).toBeInTheDocument()
    expect(screen.getByLabelText(/^Image/)).toBeInTheDocument()
  })

  it('disables the image button with the given reason before the file path exists', () => {
    render(
      <MarkdownEditor
        value="x"
        onChange={() => {}}
        enableAssets
        filePath={null}
        assetDisabledReason="Save post first to add images"
      />,
    )
    const imageBtn = screen.getByLabelText(/^Image/)
    expect(imageBtn).toBeDisabled()
    expect(imageBtn).toHaveAttribute('title', 'Save post first to add images')
  })
})
