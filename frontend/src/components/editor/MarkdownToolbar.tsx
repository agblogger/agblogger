import {
  Bold, Italic, Underline, Strikethrough, Highlighter,
  Heading2, Heading3, Heading4,
  List, ListOrdered,
  Link, ImagePlus, Youtube,
  TextQuote, Code, FileCode,
  Sigma, Pi,
  Superscript, StickyNote,
  Save, Maximize2, Minimize2,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { memo } from 'react'
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
  imageDisabledReason?: string
  onSave?: (() => void) | undefined
  saving?: boolean
  canSave?: boolean
  isFullscreen?: boolean
  onToggleFullscreen?: (() => void) | undefined
}

const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad|iPod/.test(navigator.userAgent)
const mod = isMac ? 'Cmd' : 'Ctrl'

type ButtonDef = {
  key: string
  label: string
  Icon: LucideIcon
  shortcut?: string
}

type ToolbarItem = ButtonDef | { separator: true }

const items: readonly ToolbarItem[] = [
  { key: 'bold', label: 'Bold', Icon: Bold, shortcut: `${mod}+B` },
  { key: 'italic', label: 'Italic', Icon: Italic, shortcut: `${mod}+I` },
  { key: 'underline', label: 'Underline', Icon: Underline, shortcut: `${mod}+U` },
  { key: 'strikethrough', label: 'Strikethrough', Icon: Strikethrough, shortcut: `${mod}+Shift+X` },
  { key: 'highlight', label: 'Highlight', Icon: Highlighter },
  { separator: true },
  { key: 'heading', label: 'Heading 2', Icon: Heading2, shortcut: `${mod}+H` },
  { key: 'h3', label: 'Heading 3', Icon: Heading3 },
  { key: 'h4', label: 'Heading 4', Icon: Heading4 },
  { separator: true },
  { key: 'bulletList', label: 'Bullet List', Icon: List, shortcut: `${mod}+Shift+8` },
  { key: 'orderedList', label: 'Ordered List', Icon: ListOrdered, shortcut: `${mod}+Shift+7` },
  { separator: true },
  { key: 'link', label: 'Link', Icon: Link, shortcut: `${mod}+K` },
  { key: 'image', label: 'Image', Icon: ImagePlus, shortcut: `${mod}+Shift+I` },
  { key: 'youtube', label: 'YouTube', Icon: Youtube },
  { separator: true },
  { key: 'blockquote', label: 'Blockquote', Icon: TextQuote, shortcut: `${mod}+Shift+.` },
  { key: 'code', label: 'Code', Icon: Code, shortcut: `${mod}+E` },
  { key: 'codeblock', label: 'Code Block', Icon: FileCode, shortcut: `${mod}+Shift+E` },
  { key: 'math', label: 'Math', Icon: Sigma },
  { key: 'mathblock', label: 'Math Block', Icon: Pi },
  { separator: true },
  { key: 'footnote', label: 'Footnote', Icon: Superscript, shortcut: `${mod}+Shift+F` },
  { key: 'note', label: 'Note', Icon: StickyNote },
]

export default memo(function MarkdownToolbar({
  textareaRef,
  value,
  onChange,
  disabled,
  onImageClick,
  imageUploading,
  imageDisabledReason,
  onSave,
  saving = false,
  canSave = true,
  isFullscreen = false,
  onToggleFullscreen,
}: MarkdownToolbarProps) {
  function handleAction(key: string) {
    if (key === 'image') return
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
    if (imageDisabledReason !== undefined) return imageDisabledReason
    if (imageUploading === true) return 'Uploading...'
    return `Image (${shortcut})`
  }

  const saveDisabled = (disabled ?? false) || saving || !canSave

  return (
    <div className="flex items-center gap-1 mb-2">
      {items.map((item, i) => {
        if ('separator' in item) {
          return (
            <div
              key={`sep-${i}`}
              role="separator"
              className="w-px h-4 bg-border mx-0.5 flex-shrink-0"
            />
          )
        }

        const { key, label, Icon, shortcut } = item
        const isImage = key === 'image'
        const isDisabled = isImage
          ? (disabled ?? false) || imageDisabledReason !== undefined || onImageClick === undefined || imageUploading === true
          : disabled
        const title = isImage
          ? imageTitle(shortcut ?? '')
          : shortcut !== undefined ? `${label} (${shortcut})` : label
        const ariaLabel = shortcut !== undefined ? `${label} (${shortcut})` : label

        if (isImage && onImageClick === undefined && imageDisabledReason === undefined) {
          return null
        }

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
            aria-label={ariaLabel}
          >
            <Icon size={16} />
          </button>
        )
      })}

      {(onSave !== undefined || onToggleFullscreen !== undefined) && (
        <div className="ml-auto flex items-center gap-1">
          {onSave !== undefined && (
            <button
              type="button"
              onClick={() => onSave()}
              disabled={saveDisabled}
              className={`p-1.5 text-muted hover:text-ink hover:bg-paper-warm rounded transition-colors
                       disabled:opacity-50 disabled:cursor-not-allowed${saving ? ' animate-pulse' : ''}`}
              title={saving ? 'Saving...' : `Save (${mod}+S)`}
              aria-label="Save"
            >
              <Save size={16} />
            </button>
          )}
          {onToggleFullscreen !== undefined && (
            <button
              type="button"
              onClick={() => onToggleFullscreen()}
              disabled={disabled}
              className="p-1.5 text-muted hover:text-ink hover:bg-paper-warm rounded transition-colors
                       disabled:opacity-50 disabled:cursor-not-allowed"
              title={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}
              aria-label={isFullscreen ? 'Exit fullscreen' : 'Enter fullscreen'}
            >
              {isFullscreen ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
            </button>
          )}
        </div>
      )}
    </div>
  )
})
