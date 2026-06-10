import { render, screen, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'

import { wrapSelection } from '../wrapSelection'
import { calloutAction } from '../toolbarActions'
import MarkdownToolbar from '../MarkdownToolbar'
import { createRef } from 'react'

describe('wrapSelection', () => {
  it('wraps selected text with bold markers', () => {
    const result = wrapSelection('hello world', 6, 11, {
      before: '**',
      after: '**',
      placeholder: 'bold text',
    })
    expect(result.newValue).toBe('hello **world**')
    expect(result.cursorStart).toBe(8)
    expect(result.cursorEnd).toBe(13)
  })

  it('inserts placeholder when no selection', () => {
    const result = wrapSelection('hello ', 6, 6, {
      before: '**',
      after: '**',
      placeholder: 'bold text',
    })
    expect(result.newValue).toBe('hello **bold text**')
    expect(result.cursorStart).toBe(8)
    expect(result.cursorEnd).toBe(17)
  })

  it('adds newline for block actions when not at line start', () => {
    const result = wrapSelection('some text', 9, 9, {
      before: '## ',
      after: '',
      placeholder: 'Heading',
      block: true,
    })
    expect(result.newValue).toBe('some text\n## Heading')
    expect(result.cursorStart).toBe(13)
    expect(result.cursorEnd).toBe(20)
  })

  it('does not add newline for block actions at line start', () => {
    const result = wrapSelection('', 0, 0, {
      before: '## ',
      after: '',
      placeholder: 'Heading',
      block: true,
    })
    expect(result.newValue).toBe('## Heading')
    expect(result.cursorStart).toBe(3)
    expect(result.cursorEnd).toBe(10)
  })

  it('wraps with code fence markers', () => {
    const result = wrapSelection('', 0, 0, {
      before: '```\n',
      after: '\n```',
      placeholder: 'code',
      block: true,
    })
    expect(result.newValue).toBe('```\ncode\n```')
    expect(result.cursorStart).toBe(4)
    expect(result.cursorEnd).toBe(8)
  })

  it('wraps selection with link syntax', () => {
    const result = wrapSelection('click here for info', 6, 10, {
      before: '[',
      after: '](url)',
      placeholder: 'link text',
    })
    expect(result.newValue).toBe('click [here](url) for info')
    expect(result.cursorStart).toBe(7)
    expect(result.cursorEnd).toBe(11)
  })

  it('linePrefix mode prefixes a single line with the given string', () => {
    const result = wrapSelection('hello world', 6, 11, {
      before: '',
      after: '',
      placeholder: 'quote text',
      linePrefix: '> ',
    })
    expect(result.newValue).toBe('hello > world')
    expect(result.cursorStart).toBe(6)
    expect(result.cursorEnd).toBe(13)
  })

  it('linePrefix mode prefixes each line of a multi-line selection', () => {
    const result = wrapSelection('line one\nline two\nline three', 0, 28, {
      before: '',
      after: '',
      placeholder: 'quote text',
      linePrefix: '> ',
    })
    expect(result.newValue).toBe('> line one\n> line two\n> line three')
    expect(result.cursorStart).toBe(0)
    expect(result.cursorEnd).toBe(34)
  })

  it('linePrefix mode uses placeholder when nothing is selected', () => {
    const result = wrapSelection('hello ', 6, 6, {
      before: '',
      after: '',
      placeholder: 'quote text',
      linePrefix: '> ',
    })
    expect(result.newValue).toBe('hello > quote text')
    expect(result.cursorStart).toBe(8)
    expect(result.cursorEnd).toBe(18)
  })

  it('linePrefix mode with block adds leading newline when not at line start', () => {
    const result = wrapSelection('some text', 9, 9, {
      before: '',
      after: '',
      placeholder: 'quote text',
      linePrefix: '> ',
      block: true,
    })
    expect(result.newValue).toBe('some text\n> quote text')
    expect(result.cursorStart).toBe(12)
    expect(result.cursorEnd).toBe(22)
  })

  it('linePrefix mode with block does not add newline at line start', () => {
    const result = wrapSelection('', 0, 0, {
      before: '',
      after: '',
      placeholder: 'quote text',
      linePrefix: '> ',
      block: true,
    })
    expect(result.newValue).toBe('> quote text')
    expect(result.cursorStart).toBe(2)
    expect(result.cursorEnd).toBe(12)
  })

  describe('new toolbar actions', () => {
    it('underline wraps selection with bracketed span syntax', () => {
      const result = wrapSelection('hi', 0, 2, {
        before: '[',
        after: ']{.underline}',
        placeholder: 'underlined text',
      })
      expect(result.newValue).toBe('[hi]{.underline}')
      expect(result.cursorStart).toBe(1)
      expect(result.cursorEnd).toBe(3)
    })

    it('strikethrough wraps selection with tilde markers', () => {
      const result = wrapSelection('hi', 0, 2, {
        before: '~~',
        after: '~~',
        placeholder: 'strikethrough text',
      })
      expect(result.newValue).toBe('~~hi~~')
      expect(result.cursorStart).toBe(2)
      expect(result.cursorEnd).toBe(4)
    })

    it('highlight wraps selection with equals markers', () => {
      const result = wrapSelection('hi', 0, 2, {
        before: '==',
        after: '==',
        placeholder: 'highlighted text',
      })
      expect(result.newValue).toBe('==hi==')
      expect(result.cursorStart).toBe(2)
      expect(result.cursorEnd).toBe(4)
    })

    it('h3 inserts block with leading newline and ### prefix', () => {
      const result = wrapSelection('some text', 9, 9, {
        before: '### ',
        after: '',
        placeholder: 'Heading 3',
        block: true,
      })
      expect(result.newValue).toBe('some text\n### Heading 3')
      expect(result.cursorStart).toBe(14)
      expect(result.cursorEnd).toBe(23)
    })

    it('h4 inserts block with leading newline and #### prefix', () => {
      const result = wrapSelection('some text', 9, 9, {
        before: '#### ',
        after: '',
        placeholder: 'Heading 4',
        block: true,
      })
      expect(result.newValue).toBe('some text\n#### Heading 4')
      expect(result.cursorStart).toBe(15)
      expect(result.cursorEnd).toBe(24)
    })

    it('bulletList prefixes each selected line with "- "', () => {
      const result = wrapSelection('line one\nline two', 0, 17, {
        before: '',
        after: '',
        placeholder: 'list item',
        linePrefix: '- ',
        block: true,
      })
      expect(result.newValue).toBe('- line one\n- line two')
      expect(result.cursorStart).toBe(0)
      expect(result.cursorEnd).toBe(21)
    })

    it('orderedList prefixes each selected line with "1. "', () => {
      const result = wrapSelection('line one\nline two', 0, 17, {
        before: '',
        after: '',
        placeholder: 'list item',
        linePrefix: '1. ',
        block: true,
      })
      expect(result.newValue).toBe('1. line one\n1. line two')
      expect(result.cursorStart).toBe(0)
      expect(result.cursorEnd).toBe(23)
    })

    it('youtube inserts iframe block with VIDEO_ID placeholder selected', () => {
      const result = wrapSelection('some text', 9, 9, {
        before: '<iframe src="https://www.youtube.com/embed/',
        after: '" allowfullscreen></iframe>',
        placeholder: 'VIDEO_ID',
        block: true,
      })
      expect(result.newValue).toBe(
        'some text\n<iframe src="https://www.youtube.com/embed/VIDEO_ID" allowfullscreen></iframe>',
      )
      expect(result.cursorStart).toBe(53)
      expect(result.cursorEnd).toBe(61)
    })

    it('footnote wraps selection in ^[...] syntax', () => {
      const result = wrapSelection('hello world', 6, 11, {
        before: '^[',
        after: ']',
        placeholder: 'footnote text',
      })
      expect(result.newValue).toBe('hello ^[world]')
      expect(result.cursorStart).toBe(8)
      expect(result.cursorEnd).toBe(13)
    })

    it('footnote inserts placeholder when nothing is selected', () => {
      const result = wrapSelection('hello ', 6, 6, {
        before: '^[',
        after: ']',
        placeholder: 'footnote text',
      })
      expect(result.newValue).toBe('hello ^[footnote text]')
      expect(result.cursorStart).toBe(8)
      expect(result.cursorEnd).toBe(21)
    })

    it('calloutAction generates a WrapAction with the correct shape', () => {
      const action = calloutAction('note')
      expect(action).toEqual({
        before: '::: {.note}\n',
        after: '\n:::',
        placeholder: 'note text',
        block: true,
      })
    })

    it('note action inserts fenced div at document start', () => {
      const action = calloutAction('note')
      const result = wrapSelection('', 0, 0, action)
      expect(result.newValue).toBe('::: {.note}\nnote text\n:::')
      expect(result.cursorStart).toBe(12)
      expect(result.cursorEnd).toBe(21)
    })

    it('note action adds leading newline when not at line start', () => {
      const action = calloutAction('note')
      const result = wrapSelection('some text', 9, 9, action)
      expect(result.newValue).toBe('some text\n::: {.note}\nnote text\n:::')
      expect(result.cursorStart).toBe(22)
      expect(result.cursorEnd).toBe(31)
    })

    it('math wraps selected text with $ delimiters', () => {
      const result = wrapSelection('hello world', 6, 11, {
        before: '$',
        after: '$',
        placeholder: 'x^2',
      })
      expect(result.newValue).toBe('hello $world$')
      expect(result.cursorStart).toBe(7)
      expect(result.cursorEnd).toBe(12)
    })

    it('math inserts placeholder when nothing is selected', () => {
      const result = wrapSelection('hello ', 6, 6, {
        before: '$',
        after: '$',
        placeholder: 'x^2',
      })
      expect(result.newValue).toBe('hello $x^2$')
      expect(result.cursorStart).toBe(7)
      expect(result.cursorEnd).toBe(10)
    })

    it('mathblock wraps with $$ delimiters at document start', () => {
      const result = wrapSelection('', 0, 0, {
        before: '$$\n',
        after: '\n$$',
        placeholder: '\\sum_{i=0}^n i^2',
        block: true,
      })
      expect(result.newValue).toBe('$$\n\\sum_{i=0}^n i^2\n$$')
      expect(result.cursorStart).toBe(3)
      expect(result.cursorEnd).toBe(19)
    })

    it('mathblock adds leading newline when not at line start', () => {
      const result = wrapSelection('some text', 9, 9, {
        before: '$$\n',
        after: '\n$$',
        placeholder: '\\sum_{i=0}^n i^2',
        block: true,
      })
      expect(result.newValue).toBe('some text\n$$\n\\sum_{i=0}^n i^2\n$$')
      expect(result.cursorStart).toBe(13)
      expect(result.cursorEnd).toBe(29)
    })
  })
})

describe('MarkdownToolbar', () => {
  it('renders all 20 toolbar buttons including image, footnote, note, math, and math block', () => {
    const ref = createRef<HTMLTextAreaElement>()
    render(
      <MarkdownToolbar textareaRef={ref} onChange={() => {}} onImageClick={() => {}} />,
    )
    expect(screen.getByLabelText(/^Bold/)).toBeInTheDocument()
    expect(screen.getByLabelText(/^Italic/)).toBeInTheDocument()
    expect(screen.getByLabelText(/^Underline/)).toBeInTheDocument()
    expect(screen.getByLabelText(/^Strikethrough/)).toBeInTheDocument()
    expect(screen.getByLabelText(/^Highlight/)).toBeInTheDocument()
    expect(screen.getByLabelText(/^Heading 2/)).toBeInTheDocument()
    expect(screen.getByLabelText(/^Heading 3/)).toBeInTheDocument()
    expect(screen.getByLabelText(/^Heading 4/)).toBeInTheDocument()
    expect(screen.getByLabelText(/^Bullet List/)).toBeInTheDocument()
    expect(screen.getByLabelText(/^Ordered List/)).toBeInTheDocument()
    expect(screen.getByLabelText(/^Link/)).toBeInTheDocument()
    expect(screen.getByLabelText(/^Image/)).toBeInTheDocument()
    expect(screen.getByLabelText(/^YouTube/)).toBeInTheDocument()
    expect(screen.getByLabelText(/^Blockquote/)).toBeInTheDocument()
    expect(screen.getByLabelText(/^Code \(/)).toBeInTheDocument()
    expect(screen.getByLabelText(/^Code Block/)).toBeInTheDocument()
    expect(screen.getByLabelText(/^Footnote/)).toBeInTheDocument()
    expect(screen.getByLabelText(/^Note/)).toBeInTheDocument()
    expect(screen.getByLabelText(/^Math$/)).toBeInTheDocument()
    expect(screen.getByLabelText(/^Math Block/)).toBeInTheDocument()
  })

  it('blockquote button inserts with linePrefix mode', async () => {
    const onChange = vi.fn()
    const textarea = document.createElement('textarea')
    textarea.value = 'line one\nline two'
    textarea.selectionStart = 0
    textarea.selectionEnd = 17
    const ref = { current: textarea }

    const user = userEvent.setup()
    render(
      <MarkdownToolbar textareaRef={ref} onChange={onChange} />,
    )

    await user.click(screen.getByLabelText(/^Blockquote/))

    expect(onChange).toHaveBeenCalledWith('> line one\n> line two')
  })

  it('disables all buttons when disabled prop is true', () => {
    const ref = createRef<HTMLTextAreaElement>()
    render(
      <MarkdownToolbar textareaRef={ref} onChange={() => {}} disabled />,
    )
    const buttons = screen.getAllByRole('button')
    buttons.forEach((btn) => expect(btn).toBeDisabled())
  })

  it('button click calls onChange with wrapped text', async () => {
    const onChange = vi.fn()
    const textarea = document.createElement('textarea')
    textarea.value = 'hello world'
    textarea.selectionStart = 6
    textarea.selectionEnd = 11
    // Create a ref-like object
    const ref = { current: textarea }

    const user = userEvent.setup()
    render(
      <MarkdownToolbar textareaRef={ref} onChange={onChange} />,
    )

    await user.click(screen.getByLabelText(/^Bold/))

    expect(onChange).toHaveBeenCalledWith('hello **world**')
  })

  it('heading button inserts with block mode newline', async () => {
    const onChange = vi.fn()
    const textarea = document.createElement('textarea')
    textarea.value = 'some text'
    textarea.selectionStart = 9
    textarea.selectionEnd = 9
    const ref = { current: textarea }

    const user = userEvent.setup()
    render(
      <MarkdownToolbar textareaRef={ref} onChange={onChange} />,
    )

    await user.click(screen.getByLabelText(/^Heading 2/))

    expect(onChange).toHaveBeenCalledWith('some text\n## Heading')
  })

  it('does not call onChange when textarea ref is null', async () => {
    const onChange = vi.fn()
    const ref = { current: null }

    const user = userEvent.setup()
    render(
      <MarkdownToolbar textareaRef={ref} onChange={onChange} />,
    )

    await user.click(screen.getByLabelText(/^Bold/))

    expect(onChange).not.toHaveBeenCalled()
  })

  it('shows keyboard shortcuts in button titles', () => {
    const ref = createRef<HTMLTextAreaElement>()
    render(
      <MarkdownToolbar textareaRef={ref} onChange={() => {}} />,
    )
    const boldBtn = screen.getByRole('button', { name: /Bold/ })
    expect(boldBtn.title).toMatch(/Bold \((Cmd|Ctrl)\+B\)/)

    const italicBtn = screen.getByRole('button', { name: /Italic/ })
    expect(italicBtn.title).toMatch(/Italic \((Cmd|Ctrl)\+I\)/)

    const codeBlockBtn = screen.getByRole('button', { name: /Code Block/ })
    expect(codeBlockBtn.title).toMatch(/Code Block \((Cmd|Ctrl)\+Shift\+E\)/)
  })

  it('image button calls onImageClick when provided', async () => {
    const onImageClick = vi.fn()
    const ref = createRef<HTMLTextAreaElement>()
    const user = userEvent.setup()

    render(
      <MarkdownToolbar
        textareaRef={ref}

        onChange={() => {}}
        onImageClick={onImageClick}
      />,
    )

    await user.click(screen.getByLabelText(/^Image/))
    expect(onImageClick).toHaveBeenCalledOnce()
  })

  it('does not render the image button when no image support is wired', () => {
    const ref = createRef<HTMLTextAreaElement>()
    render(<MarkdownToolbar textareaRef={ref} onChange={() => {}} />)
    expect(screen.queryByLabelText(/^Image/)).not.toBeInTheDocument()
  })

  it('image button is disabled when imageUploading is true', () => {
    const ref = createRef<HTMLTextAreaElement>()
    render(
      <MarkdownToolbar
        textareaRef={ref}

        onChange={() => {}}
        onImageClick={() => {}}
        imageUploading
      />,
    )

    expect(screen.getByLabelText(/^Image/)).toBeDisabled()
  })

  it('image button shows imageDisabledReason as tooltip when provided', () => {
    const ref = createRef<HTMLTextAreaElement>()
    render(
      <MarkdownToolbar
        textareaRef={ref}

        onChange={() => {}}
        imageDisabledReason="Save post first to add images"
      />,
    )

    const imageBtn = screen.getByLabelText(/^Image/)
    expect(imageBtn).toBeDisabled()
    expect(imageBtn).toHaveAttribute('title', 'Save post first to add images')
  })

  it('image button shows provided disabled reason as tooltip', () => {
    const ref = createRef<HTMLTextAreaElement>()
    render(
      <MarkdownToolbar
        textareaRef={ref}

        onChange={() => {}}
        imageDisabledReason="Save post first to add images"
      />,
    )

    const imageBtn = screen.getByLabelText(/^Image/)
    expect(imageBtn).toBeDisabled()
    expect(imageBtn).toHaveAttribute('title', 'Save post first to add images')
  })

  it('image button is enabled when onImageClick is provided and no imageDisabledReason', () => {
    const onImageClick = vi.fn()
    const ref = createRef<HTMLTextAreaElement>()
    render(
      <MarkdownToolbar
        textareaRef={ref}

        onChange={() => {}}
        onImageClick={onImageClick}
      />,
    )

    expect(screen.getByLabelText(/^Image/)).not.toBeDisabled()
  })

  it('does not render save or fullscreen buttons by default', () => {
    const ref = createRef<HTMLTextAreaElement>()
    render(<MarkdownToolbar textareaRef={ref} onChange={() => {}} />)
    expect(screen.queryByLabelText('Save')).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/fullscreen/i)).not.toBeInTheDocument()
  })

  it('save button calls onSave when enabled', async () => {
    const onSave = vi.fn()
    const ref = createRef<HTMLTextAreaElement>()
    const user = userEvent.setup()
    render(<MarkdownToolbar textareaRef={ref} onChange={() => {}} onSave={onSave} />)
    await user.click(screen.getByLabelText('Save'))
    expect(onSave).toHaveBeenCalledOnce()
  })

  it('save button is disabled when canSave is false', () => {
    const onSave = vi.fn()
    const ref = createRef<HTMLTextAreaElement>()
    render(
      <MarkdownToolbar textareaRef={ref} onChange={() => {}} onSave={onSave} canSave={false} />,
    )
    expect(screen.getByLabelText('Save')).toBeDisabled()
  })

  it('save button is disabled and shows Saving… while saving', () => {
    const onSave = vi.fn()
    const ref = createRef<HTMLTextAreaElement>()
    render(
      <MarkdownToolbar textareaRef={ref} onChange={() => {}} onSave={onSave} saving />,
    )
    const btn = screen.getByLabelText('Save')
    expect(btn).toBeDisabled()
    expect(btn).toHaveAttribute('title', 'Saving...')
  })

  it('fullscreen button toggles and reflects state in its label', async () => {
    const onToggleFullscreen = vi.fn()
    const ref = createRef<HTMLTextAreaElement>()
    const user = userEvent.setup()
    const { rerender } = render(
      <MarkdownToolbar
        textareaRef={ref}

        onChange={() => {}}
        onToggleFullscreen={onToggleFullscreen}
      />,
    )
    await user.click(screen.getByLabelText('Enter fullscreen'))
    expect(onToggleFullscreen).toHaveBeenCalledOnce()

    rerender(
      <MarkdownToolbar
        textareaRef={ref}

        onChange={() => {}}
        onToggleFullscreen={onToggleFullscreen}
        isFullscreen
      />,
    )
    expect(screen.getByLabelText('Exit fullscreen')).toBeInTheDocument()
  })

  it('renders 5 group separators between button groups', () => {
    const ref = createRef<HTMLTextAreaElement>()
    render(<MarkdownToolbar textareaRef={ref} onChange={() => {}} />)
    expect(screen.getAllByRole('separator')).toHaveLength(5)
  })

  it('underline button inserts bracketed span syntax', async () => {
    const onChange = vi.fn()
    const textarea = document.createElement('textarea')
    textarea.value = 'hello world'
    textarea.selectionStart = 6
    textarea.selectionEnd = 11
    const ref = { current: textarea }

    const user = userEvent.setup()
    render(<MarkdownToolbar textareaRef={ref} onChange={onChange} />)
    await user.click(screen.getByLabelText(/^Underline/))
    expect(onChange).toHaveBeenCalledWith('hello [world]{.underline}')
  })

  it('strikethrough button wraps selection with tilde markers', async () => {
    const onChange = vi.fn()
    const textarea = document.createElement('textarea')
    textarea.value = 'hello world'
    textarea.selectionStart = 6
    textarea.selectionEnd = 11
    const ref = { current: textarea }

    const user = userEvent.setup()
    render(<MarkdownToolbar textareaRef={ref} onChange={onChange} />)
    await user.click(screen.getByLabelText(/^Strikethrough/))
    expect(onChange).toHaveBeenCalledWith('hello ~~world~~')
  })

  it('highlight button wraps selection with equals markers', async () => {
    const onChange = vi.fn()
    const textarea = document.createElement('textarea')
    textarea.value = 'hello world'
    textarea.selectionStart = 6
    textarea.selectionEnd = 11
    const ref = { current: textarea }

    const user = userEvent.setup()
    render(<MarkdownToolbar textareaRef={ref} onChange={onChange} />)
    await user.click(screen.getByLabelText(/^Highlight/))
    expect(onChange).toHaveBeenCalledWith('hello ==world==')
  })

  it('bullet list button prefixes each selected line', async () => {
    const onChange = vi.fn()
    const textarea = document.createElement('textarea')
    textarea.value = 'line one\nline two'
    textarea.selectionStart = 0
    textarea.selectionEnd = 17
    const ref = { current: textarea }

    const user = userEvent.setup()
    render(<MarkdownToolbar textareaRef={ref} onChange={onChange} />)
    await user.click(screen.getByLabelText(/^Bullet List/))
    expect(onChange).toHaveBeenCalledWith('- line one\n- line two')
  })

  it('ordered list button prefixes each selected line', async () => {
    const onChange = vi.fn()
    const textarea = document.createElement('textarea')
    textarea.value = 'line one\nline two'
    textarea.selectionStart = 0
    textarea.selectionEnd = 17
    const ref = { current: textarea }

    const user = userEvent.setup()
    render(<MarkdownToolbar textareaRef={ref} onChange={onChange} />)
    await user.click(screen.getByLabelText(/^Ordered List/))
    expect(onChange).toHaveBeenCalledWith('1. line one\n1. line two')
  })

  it('youtube button inserts iframe placeholder with VIDEO_ID selected', async () => {
    const onChange = vi.fn()
    const textarea = document.createElement('textarea')
    textarea.value = ''
    textarea.selectionStart = 0
    textarea.selectionEnd = 0
    const ref = { current: textarea }

    const user = userEvent.setup()
    render(<MarkdownToolbar textareaRef={ref} onChange={onChange} />)
    await user.click(screen.getByLabelText(/^YouTube/))
    expect(onChange).toHaveBeenCalledWith(
      '<iframe src="https://www.youtube.com/embed/VIDEO_ID" allowfullscreen></iframe>',
    )
  })

  it('footnote button wraps selection in ^[...] syntax', async () => {
    const onChange = vi.fn()
    const textarea = document.createElement('textarea')
    textarea.value = 'hello world'
    textarea.selectionStart = 6
    textarea.selectionEnd = 11
    const ref = { current: textarea }

    const user = userEvent.setup()
    render(<MarkdownToolbar textareaRef={ref} onChange={onChange} />)
    await user.click(screen.getByLabelText(/^Footnote/))
    expect(onChange).toHaveBeenCalledWith('hello ^[world]')
  })

  it('note button inserts fenced div', async () => {
    const onChange = vi.fn()
    const textarea = document.createElement('textarea')
    textarea.value = ''
    textarea.selectionStart = 0
    textarea.selectionEnd = 0
    const ref = { current: textarea }

    const user = userEvent.setup()
    render(<MarkdownToolbar textareaRef={ref} onChange={onChange} />)
    await user.click(screen.getByLabelText(/^Note/))
    expect(onChange).toHaveBeenCalledWith('::: {.note}\nnote text\n:::')
  })

  it('footnote button shows keyboard shortcut in title', () => {
    const ref = createRef<HTMLTextAreaElement>()
    render(<MarkdownToolbar textareaRef={ref} onChange={() => {}} />)
    const btn = screen.getByRole('button', { name: /Footnote/ })
    expect(btn.title).toMatch(/Footnote \((Cmd|Ctrl)\+Shift\+F\)/)
  })

  it('math button wraps selection with $ delimiters', async () => {
    const onChange = vi.fn()
    const textarea = document.createElement('textarea')
    textarea.value = 'hello world'
    textarea.selectionStart = 6
    textarea.selectionEnd = 11
    const ref = { current: textarea }

    const user = userEvent.setup()
    render(<MarkdownToolbar textareaRef={ref} onChange={onChange} />)
    await user.click(screen.getByLabelText(/^Math$/))
    expect(onChange).toHaveBeenCalledWith('hello $world$')
  })

  it('math block button inserts $$ block with placeholder', async () => {
    const onChange = vi.fn()
    const textarea = document.createElement('textarea')
    textarea.value = ''
    textarea.selectionStart = 0
    textarea.selectionEnd = 0
    const ref = { current: textarea }

    const user = userEvent.setup()
    render(<MarkdownToolbar textareaRef={ref} onChange={onChange} />)
    await user.click(screen.getByLabelText(/^Math Block/))
    expect(onChange).toHaveBeenCalledWith('$$\n\\sum_{i=0}^n i^2\n$$')
  })

  describe('overflow dropdown', () => {
    let capturedObserver!: ResizeObserverCallback

    beforeEach(() => {
      vi.stubGlobal(
        'ResizeObserver',
        vi.fn(function (cb: ResizeObserverCallback) {
          capturedObserver = cb
          return { observe: vi.fn(), disconnect: vi.fn(), unobserve: vi.fn() }
        }),
      )
    })

    afterEach(() => {
      vi.unstubAllGlobals()
    })

    // Sets container offsetWidth=120, all buttons/separators to 28px each.
    // GAP=4. availableWidth = 120 - 28(overflowBtn) - 0(rightGroup) - 8(2×gap) = 84.
    // Bold(28+4=32, sum=32 ≤ 84 ✓), Italic(sum=64 ≤ 84 ✓), Underline(sum=96 > 84 ✗)
    // → overflowFrom=2 (Underline and everything after it overflows)
    function makeNarrow(toolbarEl: HTMLElement) {
      Object.defineProperty(toolbarEl, 'offsetWidth', { configurable: true, value: 120 })
      toolbarEl.querySelectorAll('button, [role="separator"]').forEach((el) => {
        Object.defineProperty(el, 'offsetWidth', { configurable: true, value: 28 })
      })
      act(() => capturedObserver([], {} as ResizeObserver))
    }

    it('overflow button is hidden when all buttons fit', () => {
      const ref = createRef<HTMLTextAreaElement>()
      const { container } = render(<MarkdownToolbar textareaRef={ref} onChange={() => {}} />)
      const toolbarEl = container.firstChild as HTMLElement
      const btn = toolbarEl.querySelector('[aria-label="More formatting options"]') as HTMLElement
      expect(btn).not.toBeNull()
      expect(btn.style.visibility).toBe('hidden')
    })

    it('overflow button becomes visible when container is narrow', () => {
      const ref = createRef<HTMLTextAreaElement>()
      const { container } = render(<MarkdownToolbar textareaRef={ref} onChange={() => {}} />)
      makeNarrow(container.firstChild as HTMLElement)
      const toolbarEl = container.firstChild as HTMLElement
      const btn = toolbarEl.querySelector('[aria-label="More formatting options"]') as HTMLElement
      expect(btn.style.visibility).toBe('visible')
    })

    it('clicking overflow button opens dropdown with overflow items', async () => {
      const user = userEvent.setup()
      const ref = createRef<HTMLTextAreaElement>()
      const { container } = render(
        <MarkdownToolbar textareaRef={ref} onChange={() => {}} />,
      )
      makeNarrow(container.firstChild as HTMLElement)
      await user.click(screen.getByLabelText('More formatting options'))
      expect(screen.getByRole('menu')).toBeInTheDocument()
      // Underline (index 2) is the first overflow item
      expect(screen.getByRole('menuitem', { name: 'Underline' })).toBeInTheDocument()
    })

    it('clicking dropdown item fires action and closes dropdown', async () => {
      const onChange = vi.fn()
      const user = userEvent.setup()
      const textarea = document.createElement('textarea')
      textarea.value = 'hello world'
      textarea.selectionStart = 6
      textarea.selectionEnd = 11
      const ref = { current: textarea }
      const { container } = render(
        <MarkdownToolbar textareaRef={ref} onChange={onChange} />,
      )
      makeNarrow(container.firstChild as HTMLElement)
      await user.click(screen.getByLabelText('More formatting options'))
      await user.click(screen.getByRole('menuitem', { name: 'Underline' }))
      expect(onChange).toHaveBeenCalledWith('hello [world]{.underline}')
      expect(screen.queryByRole('menu')).toBeNull()
    })

    it('clicking outside the dropdown closes it', async () => {
      const user = userEvent.setup()
      const ref = createRef<HTMLTextAreaElement>()
      const { container } = render(
        <MarkdownToolbar textareaRef={ref} onChange={() => {}} />,
      )
      makeNarrow(container.firstChild as HTMLElement)
      await user.click(screen.getByLabelText('More formatting options'))
      expect(screen.getByRole('menu')).toBeInTheDocument()
      await user.click(document.body)
      expect(screen.queryByRole('menu')).toBeNull()
    })

    it('pressing Escape closes the dropdown', async () => {
      const user = userEvent.setup()
      const ref = createRef<HTMLTextAreaElement>()
      const { container } = render(
        <MarkdownToolbar textareaRef={ref} onChange={() => {}} />,
      )
      makeNarrow(container.firstChild as HTMLElement)
      await user.click(screen.getByLabelText('More formatting options'))
      expect(screen.getByRole('menu')).toBeInTheDocument()
      await user.keyboard('{Escape}')
      expect(screen.queryByRole('menu')).toBeNull()
    })

    it('save and fullscreen are always rendered regardless of overflow', () => {
      const ref = createRef<HTMLTextAreaElement>()
      const { container } = render(
        <MarkdownToolbar
          textareaRef={ref}

          onChange={() => {}}
          onSave={vi.fn()}
          onToggleFullscreen={vi.fn()}
        />,
      )
      makeNarrow(container.firstChild as HTMLElement)
      expect(screen.getByLabelText('Save')).toBeInTheDocument()
      expect(screen.getByLabelText('Enter fullscreen')).toBeInTheDocument()
    })
  })
})
