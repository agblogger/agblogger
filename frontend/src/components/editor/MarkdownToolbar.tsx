import { Bold, Italic, Heading2, Link, ImagePlus, TextQuote, Code, FileCode } from 'lucide-react'
import type { RefObject } from 'react'
import { actions } from './toolbarActions'
import { wrapSelection } from './wrapSelection'

interface MarkdownToolbarProps {
  textareaRef: RefObject<HTMLTextAreaElement | null>
  value: string
  onChange: (value: string) => void
  disabled?: boolean
  onImageClick?: (() => void) | undefined
  imageUploading?: boolean
}

const isMac = typeof navigator !== 'undefined' && navigator.platform.toUpperCase().includes('MAC')
const mod = isMac ? 'Cmd' : 'Ctrl'

const buttons = [
  { key: 'bold', label: 'Bold', Icon: Bold, shortcut: `${mod}+B` },
  { key: 'italic', label: 'Italic', Icon: Italic, shortcut: `${mod}+I` },
  { key: 'heading', label: 'Heading', Icon: Heading2, shortcut: `${mod}+H` },
  { key: 'link', label: 'Link', Icon: Link, shortcut: `${mod}+K` },
  { key: 'image', label: 'Image', Icon: ImagePlus, shortcut: `${mod}+Shift+I` },
  { key: 'blockquote', label: 'Blockquote', Icon: TextQuote, shortcut: `${mod}+Shift+.` },
  { key: 'code', label: 'Code', Icon: Code, shortcut: `${mod}+E` },
  { key: 'codeblock', label: 'Code Block', Icon: FileCode, shortcut: `${mod}+Shift+E` },
] as const

export default function MarkdownToolbar({
  textareaRef,
  value,
  onChange,
  disabled,
  onImageClick,
  imageUploading,
}: MarkdownToolbarProps) {
  function handleAction(key: string) {
    if (key === 'image') return // handled via onImageClick
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

  function imageTitle(shortcut: string): string {
    if (onImageClick === undefined) return 'Save post first to add images'
    if (imageUploading === true) return 'Uploading...'
    return `Image (${shortcut})`
  }

  return (
    <div className="flex items-center gap-1 mb-2">
      {buttons.map(({ key, label, Icon, shortcut }) => {
        const isImage = key === 'image'
        const isDisabled = isImage
          ? (disabled ?? false) || onImageClick === undefined || imageUploading === true
          : disabled
        const title = isImage ? imageTitle(shortcut) : `${label} (${shortcut})`

        return (
          <button
            key={key}
            type="button"
            onClick={() => (isImage ? onImageClick?.() : handleAction(key))}
            disabled={isDisabled}
            className={`p-1.5 text-muted hover:text-ink hover:bg-paper-warm rounded transition-colors
                     disabled:opacity-50 disabled:cursor-not-allowed${
                       isImage && imageUploading === true ? ' animate-pulse' : ''
                     }`}
            title={title}
            aria-label={`${label} (${shortcut})`}
          >
            <Icon size={16} />
          </button>
        )
      })}
    </div>
  )
}
