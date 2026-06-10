/**
 * Pure helpers backing the markdown editor's textarea key handling: Tab
 * indentation, plus the logical-line Home/End and page-move FALLBACKS.
 *
 * Visual (word-wrap-aware) Home/End/PageUp/PageDown are driven natively in the
 * browser via `Selection.modify` in `MarkdownEditor`; these pure helpers are the
 * fallback used only when no live layout exists (e.g. jsdom under test, SSR).
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
export function lineStartIndex(value: string, pos: number): number {
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
  const lines = region.split('\n')
  const lineCount = lines.length
  const indented = lines.map((line) => INDENT + line).join('\n')
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
