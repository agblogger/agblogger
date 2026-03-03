import { Bold, Italic, Heading2, Link, Code, FileCode } from 'lucide-react'
import type { RefObject } from 'react'
import { actions } from './toolbarActions'
import { wrapSelection } from './wrapSelection'

interface MarkdownToolbarProps {
  textareaRef: RefObject<HTMLTextAreaElement | null>
  value: string
  onChange: (value: string) => void
  disabled?: boolean
}

const isMac = typeof navigator !== 'undefined' && navigator.platform.toUpperCase().includes('MAC')
const mod = isMac ? 'Cmd' : 'Ctrl'

const buttons = [
  { key: 'bold', label: 'Bold', Icon: Bold, shortcut: `${mod}+B` },
  { key: 'italic', label: 'Italic', Icon: Italic, shortcut: `${mod}+I` },
  { key: 'heading', label: 'Heading', Icon: Heading2, shortcut: `${mod}+H` },
  { key: 'link', label: 'Link', Icon: Link, shortcut: `${mod}+K` },
  { key: 'code', label: 'Code', Icon: Code, shortcut: `${mod}+E` },
  { key: 'codeblock', label: 'Code Block', Icon: FileCode, shortcut: `${mod}+Shift+E` },
] as const

export default function MarkdownToolbar({ textareaRef, value, onChange, disabled }: MarkdownToolbarProps) {
  function handleAction(key: string) {
    const textarea = textareaRef.current
    if (!textarea) return

    const action = actions[key]
    if (action === undefined) return
    const { newValue, cursorStart, cursorEnd } = wrapSelection(
      value,
      textarea.selectionStart,
      textarea.selectionEnd,
      action,
    )

    onChange(newValue)

    requestAnimationFrame(() => {
      textarea.focus()
      textarea.setSelectionRange(cursorStart, cursorEnd)
    })
  }

  return (
    <div className="flex items-center gap-1 mb-2">
      {buttons.map(({ key, label, Icon, shortcut }) => (
        <button
          key={key}
          type="button"
          onClick={() => handleAction(key)}
          disabled={disabled}
          className="p-1.5 text-muted hover:text-ink hover:bg-paper-warm rounded transition-colors
                   disabled:opacity-50 disabled:cursor-not-allowed"
          title={`${label} (${shortcut})`}
          aria-label={`${label} (${shortcut})`}
        >
          <Icon size={16} />
        </button>
      ))}
    </div>
  )
}
