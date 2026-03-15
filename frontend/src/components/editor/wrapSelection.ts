export interface WrapAction {
  before: string
  after: string
  placeholder: string
  block?: boolean
  linePrefix?: string
}

export function wrapSelection(
  value: string,
  selectionStart: number,
  selectionEnd: number,
  action: WrapAction,
): { newValue: string; cursorStart: number; cursorEnd: number } {
  const selected = value.slice(selectionStart, selectionEnd)
  const text = selected.length > 0 ? selected : action.placeholder

  let blockPrefix = ''
  if (action.block === true && selectionStart > 0 && value[selectionStart - 1] !== '\n') {
    blockPrefix = '\n'
  }

  if (action.linePrefix !== undefined) {
    const linePrefix = action.linePrefix
    const prefixed = text
      .split('\n')
      .map((line) => linePrefix + line)
      .join('\n')
    const inserted = blockPrefix + prefixed
    const newValue = value.slice(0, selectionStart) + inserted + value.slice(selectionEnd)
    const cursorStart = selectionStart + blockPrefix.length
    const cursorEnd = cursorStart + prefixed.length
    return { newValue, cursorStart, cursorEnd }
  }

  const before = blockPrefix + action.before
  const inserted = before + text + action.after
  const newValue = value.slice(0, selectionStart) + inserted + value.slice(selectionEnd)
  const cursorStart = selectionStart + before.length
  const cursorEnd = cursorStart + text.length
  return { newValue, cursorStart, cursorEnd }
}
