import {
  Bold, Italic, Underline, Strikethrough, Highlighter,
  Heading2, Heading3, Heading4,
  List, ListOrdered,
  Link, ImagePlus, Youtube,
  TextQuote, Code, FileCode,
  Sigma, Pi,
  Superscript, StickyNote,
  Save, Maximize2, Minimize2,
  Ellipsis,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { memo, useState, useEffect, useCallback, useRef } from 'react'
import type { RefObject } from 'react'
import { actions } from './toolbarActions'
import { wrapSelection } from './wrapSelection'

interface MarkdownToolbarProps {
  textareaRef: RefObject<HTMLTextAreaElement | null>
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
const GAP = 4 // matches gap-1 in Tailwind (4px)

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
  const containerRef = useRef<HTMLDivElement>(null)
  const itemRefs = useRef<(HTMLElement | null)[]>([])
  const overflowBtnRef = useRef<HTMLButtonElement>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)
  const rightGroupRef = useRef<HTMLDivElement>(null)

  const [overflowFrom, setOverflowFrom] = useState(items.length)
  const [dropdownOpen, setDropdownOpen] = useState(false)

  const computeOverflow = useCallback(() => {
    const container = containerRef.current
    if (!container) return
    const availableWidth =
      container.offsetWidth -
      (rightGroupRef.current?.offsetWidth ?? 0) -
      (overflowBtnRef.current?.offsetWidth ?? 0) -
      GAP * 2
    if (availableWidth <= 0) {
      setOverflowFrom(items.length)
      return
    }
    let sum = 0
    let newOverflowFrom = items.length
    for (let i = 0; i < items.length; i++) {
      const el = itemRefs.current[i]
      if (!el) continue
      const w = el.offsetWidth + GAP
      if (sum + w > availableWidth) {
        newOverflowFrom = i
        break
      }
      sum += w
    }
    setOverflowFrom(newOverflowFrom)
  }, [])

  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    const observer = new ResizeObserver(computeOverflow)
    observer.observe(container)
    return () => observer.disconnect()
  }, [computeOverflow])

  useEffect(() => {
    if (!dropdownOpen) return
    function onMouseDown(e: MouseEvent) {
      if (overflowBtnRef.current?.contains(e.target as Node) === true) return
      if (dropdownRef.current?.contains(e.target as Node) === true) return
      setDropdownOpen(false)
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') setDropdownOpen(false)
    }
    document.addEventListener('mousedown', onMouseDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onMouseDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [dropdownOpen])

  function handleAction(key: string) {
    if (key === 'image') return
    const textarea = textareaRef.current
    if (!textarea) return

    const action = actions[key]
    if (action === undefined) return
    const { newValue, cursorStart, cursorEnd } = wrapSelection(
      textarea.value,
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

  // Determine dropdown range: overflow items with leading/trailing separators trimmed
  let dropdownFirstBtn = -1
  let dropdownLastBtn = -1
  for (let i = overflowFrom; i < items.length; i++) {
    const item = items[i]
    if (item !== undefined && !('separator' in item)) {
      if (dropdownFirstBtn === -1) dropdownFirstBtn = i
      dropdownLastBtn = i
    }
  }

  return (
    <div ref={containerRef} className="relative flex items-center gap-1 mb-2">
      {items.map((item, i) => {
        const isOverflow = i >= overflowFrom
        if ('separator' in item) {
          return (
            <div
              key={`sep-${i}`}
              role="separator"
              ref={(el) => { itemRefs.current[i] = el }}
              className="w-px h-4 bg-border mx-0.5 flex-shrink-0"
              style={isOverflow
                ? { position: 'absolute', visibility: 'hidden', pointerEvents: 'none' }
                : undefined}
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
            ref={(el) => { itemRefs.current[i] = el }}
            type="button"
            onClick={() => (isImage ? onImageClick?.() : handleAction(key))}
            disabled={isDisabled}
            className={`p-1.5 text-muted hover:text-ink hover:bg-paper-warm rounded transition-colors
                     disabled:opacity-50 disabled:cursor-not-allowed${
                       isImage && imageUploading === true ? ' animate-pulse' : ''
                     }`}
            title={title}
            aria-label={ariaLabel}
            style={isOverflow
              ? { position: 'absolute', visibility: 'hidden', pointerEvents: 'none' }
              : undefined}
          >
            <Icon size={16} />
          </button>
        )
      })}

      <div className="relative">
        <button
          ref={overflowBtnRef}
          type="button"
          disabled={disabled}
          onClick={() => setDropdownOpen((o) => !o)}
          className="p-1.5 text-muted hover:text-ink hover:bg-paper-warm rounded transition-colors
                     disabled:opacity-50 disabled:cursor-not-allowed"
          title="More"
          aria-label="More formatting options"
          aria-haspopup="menu"
          aria-expanded={dropdownOpen}
          style={{ visibility: overflowFrom < items.length ? 'visible' : 'hidden' }}
        >
          <Ellipsis size={16} />
        </button>

        {dropdownOpen && dropdownFirstBtn !== -1 && (
          <div
            ref={dropdownRef}
            className="absolute right-0 top-full mt-1 z-50 min-w-[160px] rounded-md border border-border bg-paper shadow-md py-1"
            role="menu"
          >
            {Array.from({ length: dropdownLastBtn - dropdownFirstBtn + 1 }, (_, j) => {
              const idx = dropdownFirstBtn + j
              const dropItem = items[idx]
              if (dropItem === undefined) return null
              if ('separator' in dropItem) {
                return <hr key={`dsep-${idx}`} className="my-1 border-border" />
              }
              const { key, label, Icon, shortcut } = dropItem
              const isImage = key === 'image'
              const isDisabled = isImage
                ? (disabled ?? false) || imageDisabledReason !== undefined || onImageClick === undefined || imageUploading === true
                : disabled
              const title = isImage
                ? imageTitle(shortcut ?? '')
                : shortcut !== undefined ? `${label} (${shortcut})` : label
              if (isImage && onImageClick === undefined && imageDisabledReason === undefined) {
                return null
              }
              return (
                <button
                  key={key}
                  type="button"
                  onClick={() => {
                    if (isImage) {
                      onImageClick?.()
                    } else {
                      handleAction(key)
                    }
                    setDropdownOpen(false)
                  }}
                  disabled={isDisabled}
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-sm text-ink
                             hover:bg-paper-warm disabled:opacity-50 disabled:cursor-not-allowed"
                  title={title}
                  aria-label={label}
                  role="menuitem"
                >
                  <Icon size={14} />
                  <span>{label}</span>
                </button>
              )
            })}
          </div>
        )}
      </div>

      {(onSave !== undefined || onToggleFullscreen !== undefined) && (
        <div ref={rightGroupRef} className="ml-auto flex items-center gap-1 flex-shrink-0">
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
