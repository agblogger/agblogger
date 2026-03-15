import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'

import { wrapSelection } from '../wrapSelection'
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
    expect(result.cursorStart).toBe(6)
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
    expect(result.cursorStart).toBe(10)
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
    expect(result.cursorStart).toBe(0)
    expect(result.cursorEnd).toBe(12)
  })
})

describe('MarkdownToolbar', () => {
  it('renders all 8 toolbar buttons including image and blockquote', () => {
    const ref = createRef<HTMLTextAreaElement>()
    render(
      <MarkdownToolbar textareaRef={ref} value="" onChange={() => {}} />,
    )
    expect(screen.getByLabelText(/^Bold/)).toBeInTheDocument()
    expect(screen.getByLabelText(/^Italic/)).toBeInTheDocument()
    expect(screen.getByLabelText(/^Heading/)).toBeInTheDocument()
    expect(screen.getByLabelText(/^Link/)).toBeInTheDocument()
    expect(screen.getByLabelText(/^Image/)).toBeInTheDocument()
    expect(screen.getByLabelText(/^Blockquote/)).toBeInTheDocument()
    expect(screen.getByLabelText(/^Code \(/)).toBeInTheDocument()
    expect(screen.getByLabelText(/^Code Block/)).toBeInTheDocument()
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
      <MarkdownToolbar textareaRef={ref} value={'line one\nline two'} onChange={onChange} />,
    )

    await user.click(screen.getByLabelText(/^Blockquote/))

    expect(onChange).toHaveBeenCalledWith('> line one\n> line two')
  })

  it('disables all buttons when disabled prop is true', () => {
    const ref = createRef<HTMLTextAreaElement>()
    render(
      <MarkdownToolbar textareaRef={ref} value="" onChange={() => {}} disabled />,
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
      <MarkdownToolbar textareaRef={ref} value="hello world" onChange={onChange} />,
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
      <MarkdownToolbar textareaRef={ref} value="some text" onChange={onChange} />,
    )

    await user.click(screen.getByLabelText(/^Heading/))

    expect(onChange).toHaveBeenCalledWith('some text\n## Heading')
  })

  it('does not call onChange when textarea ref is null', async () => {
    const onChange = vi.fn()
    const ref = { current: null }

    const user = userEvent.setup()
    render(
      <MarkdownToolbar textareaRef={ref} value="hello" onChange={onChange} />,
    )

    await user.click(screen.getByLabelText(/^Bold/))

    expect(onChange).not.toHaveBeenCalled()
  })

  it('shows keyboard shortcuts in button titles', () => {
    const ref = createRef<HTMLTextAreaElement>()
    render(
      <MarkdownToolbar textareaRef={ref} value="" onChange={() => {}} />,
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
        value=""
        onChange={() => {}}
        onImageClick={onImageClick}
      />,
    )

    await user.click(screen.getByLabelText(/^Image/))
    expect(onImageClick).toHaveBeenCalledOnce()
  })

  it('image button is disabled when onImageClick is not provided', () => {
    const ref = createRef<HTMLTextAreaElement>()
    render(
      <MarkdownToolbar textareaRef={ref} value="" onChange={() => {}} />,
    )

    expect(screen.getByLabelText(/^Image/)).toBeDisabled()
  })

  it('image button is disabled when imageUploading is true', () => {
    const ref = createRef<HTMLTextAreaElement>()
    render(
      <MarkdownToolbar
        textareaRef={ref}
        value=""
        onChange={() => {}}
        onImageClick={() => {}}
        imageUploading
      />,
    )

    expect(screen.getByLabelText(/^Image/)).toBeDisabled()
  })
})
