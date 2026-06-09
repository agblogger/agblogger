import { describe, expect, it } from 'vitest'

import {
  dedentLines,
  indentLines,
  insertSpaces,
  lineEndTarget,
  pageTarget,
  smartHomeTarget,
} from '../textareaKeys'

describe('insertSpaces', () => {
  it('inserts spaces at a collapsed caret', () => {
    expect(insertSpaces('abcd', 2, 2, 2)).toEqual({
      value: 'ab  cd',
      selectionStart: 4,
      selectionEnd: 4,
    })
  })

  it('replaces a single-line selection with spaces', () => {
    expect(insertSpaces('abXYcd', 2, 4, 2)).toEqual({
      value: 'ab  cd',
      selectionStart: 4,
      selectionEnd: 4,
    })
  })
})

describe('indentLines', () => {
  it('indents every line a multi-line selection touches', () => {
    const value = 'one\ntwo\nthree'
    // Selection spans the start of "one" through into "two".
    const result = indentLines(value, 0, 5)
    expect(result.value).toBe('  one\n  two\nthree')
  })

  it('does not indent a trailing line the selection only touches at its start', () => {
    const value = 'one\ntwo\nthree'
    // Selection ends exactly at the start of "two" (index 4).
    const result = indentLines(value, 0, 4)
    expect(result.value).toBe('  one\ntwo\nthree')
  })

  it('shifts the selection to keep the same logical text selected', () => {
    const value = 'one\ntwo'
    const result = indentLines(value, 0, 7)
    expect(result.value).toBe('  one\n  two')
    expect(result.value.slice(result.selectionStart, result.selectionEnd)).toBe('one\n  two')
  })
})

describe('dedentLines', () => {
  it('removes up to two leading spaces per line', () => {
    const value = '    one\n  two\nthree'
    const result = dedentLines(value, 0, value.length)
    expect(result.value).toBe('  one\ntwo\nthree')
  })

  it('removes a single leading tab', () => {
    const result = dedentLines('\tone', 0, 4)
    expect(result.value).toBe('one')
  })

  it('leaves flush-left lines untouched', () => {
    const result = dedentLines('one\ntwo', 0, 7)
    expect(result.value).toBe('one\ntwo')
    expect(result.selectionStart).toBe(0)
    expect(result.selectionEnd).toBe(7)
  })

  it('clamps the selection start into the dedented line', () => {
    // Caret sits inside the leading whitespace that gets removed.
    const result = dedentLines('  ab', 1, 1)
    expect(result.value).toBe('ab')
    expect(result.selectionStart).toBe(0)
    expect(result.selectionEnd).toBe(0)
  })
})

describe('smartHomeTarget', () => {
  const value = '  hello'

  it('moves to the first non-whitespace character from line start', () => {
    expect(smartHomeTarget(value, 0)).toBe(2)
  })

  it('toggles to column zero when already at first non-whitespace', () => {
    expect(smartHomeTarget(value, 2)).toBe(0)
  })

  it('moves to first non-whitespace from mid-line', () => {
    expect(smartHomeTarget(value, 5)).toBe(2)
  })

  it('respects line boundaries on later lines', () => {
    const multiline = 'first\n    second'
    // Caret inside "second"; line starts at index 6, content at index 10.
    expect(smartHomeTarget(multiline, 12)).toBe(10)
    expect(smartHomeTarget(multiline, 10)).toBe(6)
  })
})

describe('lineEndTarget', () => {
  it('moves to the newline that ends the current line', () => {
    expect(lineEndTarget('one\ntwo', 1)).toBe(3)
  })

  it('moves to the end of the value on the last line', () => {
    expect(lineEndTarget('one\ntwo', 5)).toBe(7)
  })
})

describe('pageTarget', () => {
  const value = 'l0\nl1\nl2\nl3\nl4'

  it('moves down by the page size preserving the column', () => {
    // Caret at column 1 of line 0 (index 1).
    expect(pageTarget(value, 1, 2, 'down')).toBe(7) // line 2 ("l2") column 1
  })

  it('moves up by the page size preserving the column', () => {
    // Caret at column 1 of line 4 (index 13).
    expect(pageTarget(value, 13, 2, 'up')).toBe(7) // line 2 column 1
  })

  it('clamps at the last line', () => {
    expect(pageTarget(value, 1, 99, 'down')).toBe(13) // line 4 column 1
  })

  it('clamps at the first line', () => {
    expect(pageTarget(value, 13, 99, 'up')).toBe(1) // line 0 column 1
  })

  it('clamps the column to a shorter destination line', () => {
    const ragged = 'short\nlongerline'
    // Caret at column 9 of line 1 (index 6 + 9 = 15).
    expect(pageTarget(ragged, 15, 1, 'up')).toBe(5) // line 0 only has 5 chars
  })
})
