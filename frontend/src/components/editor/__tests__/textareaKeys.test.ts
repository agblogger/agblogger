import { describe, expect, it } from 'vitest'

import {
  dedentLines,
  indentLines,
  insertSpaces,
  lineEndTarget,
  pageTarget,
  smartHomeTarget,
  visualEndTarget,
  visualPageTarget,
  visualRowCount,
  visualRowEndTarget,
  visualRowHomeTarget,
  visualSmartHomeTarget,
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

describe('visualRowHomeTarget', () => {
  // Visual-row smart-home: toggle within the VISUAL ROW between its first
  // non-whitespace char and its start. It must never jump to the logical line
  // start on a continuation row — that was the "flies to the top of the
  // paragraph" bug.
  const wrapped = 'abcdefghijklmnopqrst' // pretend row0=[0,10), row1=[10,20)

  it('moves to the visual row start from mid continuation row', () => {
    expect(visualRowHomeTarget(wrapped, 15, 10, 20)).toBe(10)
  })

  it('stays at the visual row start instead of flying to logical column 0', () => {
    // Regression: caret already at a continuation row start must NOT go to 0.
    expect(visualRowHomeTarget(wrapped, 10, 10, 20)).toBe(10)
  })

  it('toggles first-non-whitespace and start on an indented first row', () => {
    const indented = '  hello'
    expect(visualRowHomeTarget(indented, 5, 0, 7)).toBe(2) // mid row → first non-ws
    expect(visualRowHomeTarget(indented, 2, 0, 7)).toBe(0) // at first non-ws → row start
    expect(visualRowHomeTarget(indented, 0, 0, 7)).toBe(0) // at row start → stays
  })
})

describe('visualRowEndTarget', () => {
  // Visual-row end. The wrap-boundary offset (rowEnd) must never be returned:
  // a textarea renders a caret placed there with downstream affinity, i.e. at
  // the START of the next visual row, so End would overshoot a whole row. The
  // target is the last offset that still renders on the CURRENT row. On the
  // final visual row there is no wrap after, so the true line end is safe.
  it('trims the hanging trailing space on a wrap-boundary row', () => {
    const value = 'hello world foo' // row0 = "hello world " ends with space at 11
    expect(visualRowEndTarget(value, 0, 12, 15)).toBe(11)
  })

  it('goes to the true line end on the final visual row', () => {
    const value = 'hello world foo'
    expect(visualRowEndTarget(value, 12, 15, 15)).toBe(15)
  })

  it('steps back one glyph when the wrap breaks mid-word (no trailing space)', () => {
    // rowEnd 8 is a soft-wrap boundary; landing there renders on the next row.
    // 7 is the last glyph of this row and renders on it (verified in-browser).
    const value = 'abcdefghijklmno'
    expect(visualRowEndTarget(value, 0, 8, 15)).toBe(7)
  })

  it('keeps trailing spaces on a single-row line (no wrap after)', () => {
    const value = 'hi   '
    expect(visualRowEndTarget(value, 0, 5, 5)).toBe(5)
  })
})

describe('visualRowCount', () => {
  it('returns 1 for an empty line', () => {
    expect(visualRowCount(0, 10)).toBe(1)
  })

  it('returns 1 when the line fits within one row', () => {
    expect(visualRowCount(5, 10)).toBe(1)
    expect(visualRowCount(10, 10)).toBe(1)
  })

  it('returns 2 when the line just overflows one row', () => {
    expect(visualRowCount(11, 10)).toBe(2)
  })

  it('returns ceiling of line divided by charsPerRow', () => {
    expect(visualRowCount(20, 10)).toBe(2)
    expect(visualRowCount(21, 10)).toBe(3)
  })
})

describe('visualPageTarget', () => {
  // 5 lines each 15 chars; charsPerRow=10 → 2 visual rows per line, 10 total.
  // Text positions: line0 0-14, line1 16-30, line2 32-46, line3 48-62, line4 64-78
  const line15 = '123456789012345'
  const value5 = Array(5).fill(line15).join('\n') // length 79

  it('moves down by visibleRows in visual-row space preserving visual column', () => {
    // caret at line0 col5 → visualRow 0, colInVR 5
    // PageDown visibleRows=3 → targetVR 3 (row1 of line1, vrInLine=1)
    // col = min(1*10+5, 15) = 15  →  off = 16+15 = 31
    expect(visualPageTarget(value5, 5, 10, 3, 'down')).toBe(31)
  })

  it('moves up by visibleRows in visual-row space preserving visual column', () => {
    // caret at line2 col5 → offset 37, visualRow 4, colInVR 5
    // PageUp visibleRows=3 → targetVR 1 (row1 of line0, vrInLine=1)
    // col = min(1*10+5, 15) = 15  →  off = 0+15 = 15
    expect(visualPageTarget(value5, 37, 10, 3, 'up')).toBe(15)
  })

  it('clamps at the last visual row when paging past end', () => {
    // caret at line4 col5 → offset 69, visualRow 8
    // PageDown visibleRows=3 → targetVR min(9, 11) = 9 (row1 of line4)
    // col = min(1*10+5, 15) = 15  →  off = 64+15 = 79 = value.length
    expect(visualPageTarget(value5, 69, 10, 3, 'down')).toBe(79)
  })

  it('clamps at the first visual row when paging past beginning', () => {
    // caret at line0 col5 → visualRow 0
    // PageUp visibleRows=3 → targetVR max(0, -3) = 0 (same row, no movement)
    // col = min(0*10+5, 15) = 5  →  off = 0+5 = 5
    expect(visualPageTarget(value5, 5, 10, 3, 'up')).toBe(5)
  })

  it('clamps column to a shorter destination line', () => {
    // line0='short'(5 chars), line1='123456789012345'(15 chars), charsPerRow=10
    const ragged = 'short\n123456789012345'
    // caret at line1 col12 → offset 6+12=18, visualRow=ceil(5/10)+floor(12/10)=1+1=2, colInVR=2
    // PageUp visibleRows=2 → targetVR max(0, 2-2)=0 (row0 of line0)
    // col = min(0*10+2, 5) = 2  →  off = 0+2 = 2
    expect(visualPageTarget(ragged, 18, 10, 2, 'up')).toBe(2)
  })

  it('handles a single-line value without wrapping', () => {
    const single = 'hello'
    // caret at col 2, charsPerRow 10, visibleRows 3
    // Both up and down clamp to the only visual row
    expect(visualPageTarget(single, 2, 10, 3, 'down')).toBe(2)
    expect(visualPageTarget(single, 2, 10, 3, 'up')).toBe(2)
  })
})

describe('visualSmartHomeTarget', () => {
  it('behaves identically to smartHomeTarget when the line fits in one visual row', () => {
    const value = '  hello'
    // charsPerRow 20 → vrInLine 0 everywhere → delegate to smartHomeTarget
    expect(visualSmartHomeTarget(value, 5, 20)).toBe(2)   // mid-line → first non-ws
    expect(visualSmartHomeTarget(value, 2, 20)).toBe(0)   // at first non-ws → col 0
    expect(visualSmartHomeTarget(value, 0, 20)).toBe(2)   // at col 0 → first non-ws
  })

  it('moves to the visual row start from within a continuation visual row', () => {
    const value = '1234567890abcdef'  // 16 chars, no leading whitespace
    // caret at col 13 (visual row 1, charsPerRow 10) → vrs = 10
    expect(visualSmartHomeTarget(value, 13, 10)).toBe(10)
  })

  it('falls back to logical-line smart home from the visual row start', () => {
    const value = '1234567890abcdef'
    // col 10 = visual row 1 start; smartHome: firstNonWs=0, 10≠0 → 0
    expect(visualSmartHomeTarget(value, 10, 10)).toBe(0)
  })

  it('applies smart-home whitespace toggle on first visual row of an indented line', () => {
    const value = '  1234567890abcd'  // 2 spaces + 14 chars = 16 total
    expect(visualSmartHomeTarget(value, 5, 10)).toBe(2)   // mid row0 → first non-ws
    expect(visualSmartHomeTarget(value, 2, 10)).toBe(0)   // first non-ws → col 0
    expect(visualSmartHomeTarget(value, 13, 10)).toBe(10) // col 13 (row1) → row1 start
    // row1 start → smartHome: firstNonWs=2, 10≠2 → 2
    expect(visualSmartHomeTarget(value, 10, 10)).toBe(2)
  })

  it('respects line boundaries in multi-line values', () => {
    const value = 'abc\n  1234567890xyz'  // line1 = "  1234567890xyz" starting at 4
    // line1 col 13 = abs 17, visual row 1 → vrs = 4+10 = 14
    expect(visualSmartHomeTarget(value, 17, 10)).toBe(14)
    // line1 col 10 = abs 14 = visual row 1 start → smartHome: firstNonWs=6, 14≠6 → 6
    expect(visualSmartHomeTarget(value, 14, 10)).toBe(6)
  })
})

describe('visualEndTarget', () => {
  it('goes to the logical line end when the line fits in one visual row', () => {
    expect(visualEndTarget('abc\ndef', 1, 10)).toBe(3)   // \n position
    expect(visualEndTarget('abc', 1, 10)).toBe(3)         // EOT position
  })

  it('goes to the start of the next visual row for a non-last visual row', () => {
    const value = '1234567890abcdef'  // 16 chars
    expect(visualEndTarget(value, 3, 10)).toBe(10)  // col 3, row 0 → end = 10
    expect(visualEndTarget(value, 0, 10)).toBe(10)  // col 0, row 0 → end = 10
  })

  it('goes to the logical line end from the last visual row', () => {
    const value = '1234567890abcdef'  // 16 chars
    expect(visualEndTarget(value, 12, 10)).toBe(16)  // col 12, row 1 → end = 16
  })

  it('respects line boundaries in multi-line values', () => {
    const value = 'abc\n1234567890xyz'  // line1 = "1234567890xyz" (13 chars) at pos 4
    // col 3 on line1 (abs 7), row 0 → end = 4+10 = 14
    expect(visualEndTarget(value, 7, 10)).toBe(14)
    // col 11 on line1 (abs 15), row 1 → end = 4+13 = 17 (EOT)
    expect(visualEndTarget(value, 15, 10)).toBe(17)
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
