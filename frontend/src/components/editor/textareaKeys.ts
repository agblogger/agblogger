/**
 * Pure helpers backing the markdown editor's textarea key handling: Tab
 * indentation and editor-style caret navigation (smart Home/End, page moves).
 *
 * Every function operates purely on the string value and selection offsets so
 * the logic can be unit- and property-tested without a DOM. The component layer
 * (`MarkdownEditor`) reads the live selection, calls these, and applies the
 * result back onto the textarea.
 */

export interface EditResult {
  value: string
  selectionStart: number
  selectionEnd: number
}

export type PageDirection = 'up' | 'down'

const INDENT = '  '

/** Offset of the start of the line containing `pos`. */
function lineStartIndex(value: string, pos: number): number {
  return value.lastIndexOf('\n', pos - 1) + 1
}

/** Offset of the end of the line containing `pos` (the next `\n`, or the end). */
function lineEndIndex(value: string, pos: number): number {
  const nl = value.indexOf('\n', pos)
  return nl === -1 ? value.length : nl
}

/**
 * End of the line range a selection spans. When the selection ends exactly at a
 * line start (just past a `\n`), that trailing line is not considered part of
 * the block — matching how typical editors indent a multi-line selection.
 */
function selectionLineEnd(value: string, selStart: number, selEnd: number): number {
  const endRef = selEnd > selStart && value[selEnd - 1] === '\n' ? selEnd - 1 : selEnd
  return lineEndIndex(value, endRef)
}

/** Replace the selection with `n` spaces and collapse the caret after them. */
export function insertSpaces(
  value: string,
  selStart: number,
  selEnd: number,
  n: number,
): EditResult {
  const spaces = ' '.repeat(n)
  const newValue = value.slice(0, selStart) + spaces + value.slice(selEnd)
  const cursor = selStart + n
  return { value: newValue, selectionStart: cursor, selectionEnd: cursor }
}

/** Prefix every line overlapping the selection with two spaces. */
export function indentLines(value: string, selStart: number, selEnd: number): EditResult {
  const ls = lineStartIndex(value, selStart)
  const le = selectionLineEnd(value, selStart, selEnd)
  const region = value.slice(ls, le)
  const lineCount = region.split('\n').length
  const indented = region
    .split('\n')
    .map((line) => INDENT + line)
    .join('\n')
  const newValue = value.slice(0, ls) + indented + value.slice(le)
  return {
    value: newValue,
    selectionStart: selStart + INDENT.length,
    selectionEnd: selEnd + INDENT.length * lineCount,
  }
}

/**
 * Remove up to two leading spaces (or one leading tab) from every line
 * overlapping the selection. Lines already flush left are left untouched.
 */
export function dedentLines(value: string, selStart: number, selEnd: number): EditResult {
  const ls = lineStartIndex(value, selStart)
  const le = selectionLineEnd(value, selStart, selEnd)
  const region = value.slice(ls, le)

  let firstRemoved = 0
  let totalRemoved = 0
  const dedented = region
    .split('\n')
    .map((line, index) => {
      let removed = 0
      if (line.startsWith('\t')) {
        removed = 1
      } else {
        while (removed < INDENT.length && line[removed] === ' ') removed++
      }
      if (index === 0) firstRemoved = removed
      totalRemoved += removed
      return line.slice(removed)
    })
    .join('\n')

  const newValue = value.slice(0, ls) + dedented + value.slice(le)
  const newSelStart = Math.max(ls, selStart - firstRemoved)
  return {
    value: newValue,
    selectionStart: newSelStart,
    selectionEnd: Math.max(newSelStart, selEnd - totalRemoved),
  }
}

/**
 * Smart-home target in visual-row space for a monospace textarea with wrapping.
 * - If the caret is not at the start of its visual row, move there.
 * - If already at the visual row start, apply the logical-line smart-home toggle
 *   (first non-whitespace ↔ column zero), delegating to `smartHomeTarget`.
 * For non-wrapping lines (vrInLine === 0) this is identical to `smartHomeTarget`.
 */
export function visualSmartHomeTarget(
  value: string,
  caret: number,
  charsPerRow: number,
): number {
  const ls = lineStartIndex(value, caret)
  const vrInLine = Math.floor((caret - ls) / charsPerRow)
  if (vrInLine > 0) {
    const vrs = ls + vrInLine * charsPerRow
    if (caret > vrs) return vrs
  }
  return smartHomeTarget(value, caret)
}

/**
 * End-of-visual-row target for a monospace textarea with wrapping.
 * Moves to the start of the next visual row (= one past the last char of the
 * current row). On the final visual row of a logical line this is the logical
 * line end, identical to `lineEndTarget`.
 */
export function visualEndTarget(
  value: string,
  caret: number,
  charsPerRow: number,
): number {
  const ls = lineStartIndex(value, caret)
  const le = lineEndIndex(value, caret)
  const vrInLine = Math.floor((caret - ls) / charsPerRow)
  return ls + Math.min((vrInLine + 1) * charsPerRow, le - ls)
}

/**
 * Visual-row smart-home target. Toggles within a single visual row: from
 * anywhere past the row's first non-whitespace character it moves there, and
 * from at-or-before it (including the row start) it moves to the row start.
 *
 * Crucially it stays inside the visual row — on a continuation row it never
 * jumps to the logical line start. On the first visual row of a line
 * `rowStart` equals the line start, so this reduces to classic smart-home.
 * `rowStart`/`rowEnd` are absolute offsets bounding the caret's visual row.
 */
export function visualRowHomeTarget(
  value: string,
  caret: number,
  rowStart: number,
  rowEnd: number,
): number {
  let firstNonWs = rowStart
  while (firstNonWs < rowEnd && (value[firstNonWs] === ' ' || value[firstNonWs] === '\t')) {
    firstNonWs++
  }
  return caret > firstNonWs ? firstNonWs : rowStart
}

/**
 * Visual-row end target. On a wrap-boundary row (`rowEnd` < `lineEnd`) the
 * space that caused the wrap hangs at the row's end; landing exactly on
 * `rowEnd` is the next row's start offset, which the browser renders at the
 * start of the next visual row. Trimming the trailing whitespace lands the
 * caret after the last visible glyph so it renders at the end of the current
 * row. On the final visual row it goes to the true line end (keeping any
 * trailing spaces, since nothing wraps after them).
 */
export function visualRowEndTarget(
  value: string,
  rowStart: number,
  rowEnd: number,
  lineEnd: number,
): number {
  if (rowEnd >= lineEnd) return lineEnd
  let end = rowEnd
  while (end > rowStart && (value[end - 1] === ' ' || value[end - 1] === '\t')) {
    end--
  }
  return end
}

/**
 * Smart-home target: the first non-whitespace character of the line, or column
 * zero when the caret already sits at that first non-whitespace character.
 */
export function smartHomeTarget(value: string, caret: number): number {
  const ls = lineStartIndex(value, caret)
  const le = lineEndIndex(value, caret)
  let firstNonWs = ls
  while (firstNonWs < le && (value[firstNonWs] === ' ' || value[firstNonWs] === '\t')) {
    firstNonWs++
  }
  return caret === firstNonWs ? ls : firstNonWs
}

/** End of the line containing the caret. */
export function lineEndTarget(value: string, caret: number): number {
  return lineEndIndex(value, caret)
}

/** Start offset of every line in `value`. */
function lineStarts(value: string): number[] {
  const starts = [0]
  for (let i = 0; i < value.length; i++) {
    if (value[i] === '\n') starts.push(i + 1)
  }
  return starts
}

/**
 * Number of visual rows occupied by a logical line in a monospace textarea.
 * An empty line still takes one visual row.
 */
export function visualRowCount(lineLength: number, charsPerRow: number): number {
  return lineLength === 0 ? 1 : Math.ceil(lineLength / charsPerRow)
}

/**
 * Move the caret one visual page up or down in a monospace textarea with word
 * wrap, preserving the visual column within the row. `charsPerRow` and
 * `visibleRows` are derived from DOM metrics by the caller.
 */
export function visualPageTarget(
  value: string,
  caret: number,
  charsPerRow: number,
  visibleRows: number,
  direction: PageDirection,
): number {
  const lines = value.split('\n')

  // Find caret's logical line and character column.
  let caretLine = 0
  let linePos = 0
  for (let i = 0; i < lines.length; i++) {
    if (i === lines.length - 1 || caret <= linePos + (lines[i]?.length ?? 0)) {
      caretLine = i
      break
    }
    linePos += (lines[i]?.length ?? 0) + 1
  }
  const caretCol = caret - linePos

  // Visual row of caret and column-within-that-row.
  let caretVR = 0
  for (let i = 0; i < caretLine; i++) {
    caretVR += visualRowCount(lines[i]?.length ?? 0, charsPerRow)
  }
  caretVR += Math.floor(caretCol / charsPerRow)
  const colInVR = caretCol % charsPerRow

  // Total visual rows across all lines (for clamping).
  const totalVR = lines.reduce((sum, l) => sum + visualRowCount(l.length, charsPerRow), 0)

  // Target visual row, clamped within [0, totalVR-1].
  const targetVR = Math.max(
    0,
    Math.min(totalVR - 1, direction === 'up' ? caretVR - visibleRows : caretVR + visibleRows),
  )

  // Map target visual row → character offset, preserving visual column.
  let vr = 0
  for (let i = 0; i < lines.length; i++) {
    const lVR = visualRowCount(lines[i]?.length ?? 0, charsPerRow)
    if (vr + lVR > targetVR) {
      const vrInLine = targetVR - vr
      const col = Math.min(vrInLine * charsPerRow + colInVR, lines[i]?.length ?? 0)
      let off = 0
      for (let j = 0; j < i; j++) off += (lines[j]?.length ?? 0) + 1
      return off + col
    }
    vr += lVR
  }
  return value.length
}

/**
 * Move the caret `pageLines` lines up or down, preserving the current column
 * (clamped to the destination line's length). Clamps at the first/last line.
 */
export function pageTarget(
  value: string,
  caret: number,
  pageLines: number,
  direction: PageDirection,
): number {
  const starts = lineStarts(value)
  let line = starts.length - 1
  while (line > 0 && (starts[line] ?? 0) > caret) line--
  const column = caret - (starts[line] ?? 0)

  const target =
    direction === 'up'
      ? Math.max(0, line - pageLines)
      : Math.min(starts.length - 1, line + pageLines)
  const targetStart = starts[target] ?? 0
  const targetEnd = lineEndIndex(value, targetStart)
  return Math.min(targetStart + column, targetEnd)
}
