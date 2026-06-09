import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { createPortal } from 'react-dom'
import { ChevronRight, ChevronLeft, Eye } from 'lucide-react'

import MarkdownToolbar from './MarkdownToolbar'
import { actions as toolbarActions } from './toolbarActions'
import { wrapSelection } from './wrapSelection'
import {
  dedentLines,
  indentLines,
  insertSpaces,
  lineEndTarget,
  smartHomeTarget,
  visualPageTarget,
} from './textareaKeys'
import { useScrollSync } from '@/hooks/useScrollSync'
import { useMarkdownPreview } from '@/hooks/useMarkdownPreview'
import FileStrip from './FileStrip'
import { useFileUpload } from './useFileUpload'

const KEY_MAP: Record<string, string> = { b: 'bold', i: 'italic', h: 'heading', k: 'link' }
const NAVIGATION_KEYS = new Set(['Home', 'End', 'PageUp', 'PageDown'])

export interface MarkdownEditorProps {
  value: string
  onChange: (value: string) => void
  disabled?: boolean
  onSave?: () => void
  saving?: boolean
  canSave?: boolean
  filePath?: string | null
  enableAssets?: boolean
  assetDisabledReason?: string
  editorHeight?: string
}

export default function MarkdownEditor({
  value,
  onChange,
  disabled = false,
  onSave,
  saving = false,
  canSave = true,
  filePath = null,
  enableAssets = false,
  assetDisabledReason,
  editorHeight = '80vh',
}: MarkdownEditorProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const previewRef = useRef<HTMLDivElement>(null)
  const [mobileTab, setMobileTab] = useState<'edit' | 'preview'>('edit')
  const [isFullscreen, setIsFullscreen] = useState(false)

  useEffect(() => {
    if (!isFullscreen) return
    function onKey(e: globalThis.KeyboardEvent) {
      if (e.key === 'Escape') setIsFullscreen(false)
    }
    window.addEventListener('keydown', onKey)
    // Lock background scroll so the overlay spans the full window (no scrollbar
    // gutter) and the page behind it cannot scroll.
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = previousOverflow
    }
  }, [isFullscreen])

  const [fileRefreshToken, setFileRefreshToken] = useState(0)
  const imageUploadEnabled = enableAssets && filePath !== null
  const imageDisabledReason =
    enableAssets && filePath === null ? assetDisabledReason : undefined

  function insertAtCursor(text: string) {
    const textarea = textareaRef.current
    if (!textarea) {
      onChange(value + '\n' + text)
      return
    }
    const pos = textarea.selectionStart
    onChange(value.slice(0, pos) + text + value.slice(pos))
  }

  const {
    triggerUpload: triggerImageUpload,
    uploading: imageUploading,
    inputProps: imageInputProps,
  } = useFileUpload({
    filePath: imageUploadEnabled ? filePath : null,
    accept: 'image/*',
    multiple: false,
    onSuccess: (filenames) => {
      for (const name of filenames) {
        insertAtCursor(`![${name}](${name})`)
      }
      setFileRefreshToken((prev) => prev + 1)
    },
  })

  const { syncEditorToPreview, syncPreviewToEditor } = useScrollSync({
    textareaRef,
    previewRef,
    content: value,
  })
  const { html, error: previewError, hasContent } = useMarkdownPreview({
    value,
    filePath,
    previewRef,
  })

  const saveAllowed = canSave && !saving && !disabled

  function applyAction(actionKey: string) {
    const textarea = textareaRef.current
    if (!textarea) return
    const action = toolbarActions[actionKey]
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

  function applyTab(shiftKey: boolean) {
    const textarea = textareaRef.current
    if (!textarea) return
    const start = textarea.selectionStart
    const end = textarea.selectionEnd
    const result = shiftKey
      ? dedentLines(value, start, end)
      : value.slice(start, end).includes('\n')
        ? indentLines(value, start, end)
        : insertSpaces(value, start, end, 2)
    onChange(result.value)
    requestAnimationFrame(() => {
      textarea.focus()
      textarea.setSelectionRange(result.selectionStart, result.selectionEnd)
    })
  }

  function textareaPageMetrics(textarea: HTMLTextAreaElement): { charsPerRow: number; lineHeight: number } {
    const style = window.getComputedStyle(textarea)
    let lineHeight = parseFloat(style.lineHeight)
    if (Number.isNaN(lineHeight) || lineHeight <= 0) {
      lineHeight = parseFloat(style.fontSize) * 1.2 || 16
    }
    const pl = parseFloat(style.paddingLeft) || 0
    const pr = parseFloat(style.paddingRight) || 0
    const contentWidth = textarea.clientWidth - pl - pr
    if (contentWidth <= 0) {
      return { charsPerRow: Number.MAX_SAFE_INTEGER, lineHeight }
    }
    const canvas = document.createElement('canvas')
    const ctx = canvas.getContext('2d')
    let charWidth: number
    if (ctx) {
      ctx.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`
      const w = ctx.measureText('M').width
      charWidth = w > 0 ? w : parseFloat(style.fontSize) * 0.6 || 8
    } else {
      charWidth = parseFloat(style.fontSize) * 0.6 || 8
    }
    return { charsPerRow: Math.max(1, Math.floor(contentWidth / charWidth)), lineHeight }
  }

  // Returns the visual row boundaries for the caret's position using the actual
  // browser word-wrap layout. Creates a short-lived mirror div to run Range
  // queries — accurate for any wrapping algorithm. Returns null when no layout
  // is available (JSDOM / SSR), signalling callers to fall back to logical-line
  // behavior.
  function getVisualRowBounds(
    textarea: HTMLTextAreaElement,
    caret: number,
  ): { rowStart: number; rowEnd: number } | null {
    const val = textarea.value
    const ls = val.lastIndexOf('\n', caret - 1) + 1
    const nlIdx = val.indexOf('\n', caret)
    const le = nlIdx === -1 ? val.length : nlIdx
    const line = val.slice(ls, le)

    if (line.length === 0) return { rowStart: ls, rowEnd: le }

    const caretInLine = Math.min(caret - ls, line.length - 1)
    const style = window.getComputedStyle(textarea)

    const mirror = document.createElement('div')
    mirror.style.cssText =
      `position:absolute;left:-9999px;top:0;` +
      `width:${textarea.clientWidth}px;` +
      `font-family:${style.fontFamily};` +
      `font-size:${style.fontSize};` +
      `font-weight:${style.fontWeight};` +
      `line-height:${style.lineHeight};` +
      `letter-spacing:${style.letterSpacing || '0'};` +
      `padding-left:${style.paddingLeft};` +
      `padding-right:${style.paddingRight};` +
      `white-space:pre-wrap;overflow-wrap:break-word;word-break:normal;box-sizing:border-box`
    mirror.textContent = line
    document.body.appendChild(mirror)

    const textNode = mirror.firstChild as Text
    const range = document.createRange()
    range.setStart(textNode, caretInLine)
    range.setEnd(textNode, caretInLine + 1)

    // Range.getBoundingClientRect is not available in all environments (e.g. JSDOM).
    if (typeof range.getBoundingClientRect !== 'function') {
      document.body.removeChild(mirror)
      return null
    }
    const caretRect = range.getBoundingClientRect()

    if (caretRect.height === 0) {
      document.body.removeChild(mirror)
      return null
    }

    const caretY = caretRect.top

    // Binary search for the first char on the current visual row.
    let lo = 0
    let hi = caretInLine
    while (lo < hi) {
      const mid = Math.floor((lo + hi) / 2)
      range.setStart(textNode, mid)
      range.setEnd(textNode, mid + 1)
      if (range.getBoundingClientRect().top < caretY) lo = mid + 1
      else hi = mid
    }
    const rowStartInLine = lo

    // Binary search for the first char on the NEXT visual row (= exclusive row end).
    lo = caretInLine
    hi = line.length
    while (lo < hi) {
      const mid = Math.floor((lo + hi) / 2)
      range.setStart(textNode, mid)
      range.setEnd(textNode, mid + 1)
      if (range.getBoundingClientRect().top <= caretY) lo = mid + 1
      else hi = mid
    }
    const rowEndInLine = lo

    document.body.removeChild(mirror)
    return { rowStart: ls + rowStartInLine, rowEnd: ls + rowEndInLine }
  }

  function applyNavigation(key: string, shiftKey: boolean) {
    const textarea = textareaRef.current
    if (!textarea) return
    const start = textarea.selectionStart
    const end = textarea.selectionEnd
    const backward = textarea.selectionDirection === 'backward'
    const collapsed = start === end
    const anchor = collapsed ? start : backward ? end : start
    const active = collapsed ? start : backward ? start : end

    if (key === 'PageUp' || key === 'PageDown') {
      const { charsPerRow, lineHeight } = textareaPageMetrics(textarea)
      const visibleRows = Math.max(1, Math.floor(textarea.clientHeight / lineHeight) - 1)
      const direction = key === 'PageUp' ? 'up' : 'down'
      const target = visualPageTarget(value, active, charsPerRow, visibleRows, direction)
      const scrollTop = Math.max(
        0,
        Math.min(
          textarea.scrollHeight - textarea.clientHeight,
          direction === 'up'
            ? textarea.scrollTop - textarea.clientHeight
            : textarea.scrollTop + textarea.clientHeight,
        ),
      )
      // Defer to the next frame so setSelectionRange + scrollTop take effect
      // after e.preventDefault() has fully suppressed the browser's default.
      requestAnimationFrame(() => {
        if (shiftKey) {
          const newStart = Math.min(anchor, target)
          const newEnd = Math.max(anchor, target)
          textarea.setSelectionRange(newStart, newEnd, target < anchor ? 'backward' : 'forward')
        } else {
          textarea.setSelectionRange(target, target)
        }
        textarea.scrollTop = scrollTop
      })
      return
    }

    // Home / End: query the actual browser word-wrap layout via a mirror div.
    const bounds = getVisualRowBounds(textarea, active)
    let target: number
    if (key === 'Home') {
      if (bounds !== null) {
        // At visual row start: smart-home toggle (first non-ws ↔ col 0).
        // Past visual row start: jump there first.
        target = active > bounds.rowStart ? bounds.rowStart : smartHomeTarget(value, active)
      } else {
        target = smartHomeTarget(value, active)
      }
    } else {
      target = bounds !== null ? bounds.rowEnd : lineEndTarget(value, active)
    }

    if (shiftKey) {
      const newStart = Math.min(anchor, target)
      const newEnd = Math.max(anchor, target)
      textarea.setSelectionRange(newStart, newEnd, target < anchor ? 'backward' : 'forward')
    } else {
      textarea.setSelectionRange(target, target)
    }
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    const hasOtherMod = e.metaKey || e.ctrlKey || e.altKey

    if (e.key === 'Tab' && !hasOtherMod) {
      e.preventDefault()
      applyTab(e.shiftKey)
      return
    }

    if (!hasOtherMod && NAVIGATION_KEYS.has(e.key)) {
      e.preventDefault()
      applyNavigation(e.key, e.shiftKey)
      return
    }

    const isMod = e.metaKey || e.ctrlKey
    if (!isMod) return

    if ((e.key === 's' || e.key === 'S') && !e.shiftKey) {
      if (onSave !== undefined && saveAllowed) {
        e.preventDefault()
        onSave()
      }
      return
    }

    if ((e.key === 'i' || e.key === 'I') && e.shiftKey) {
      if (imageUploadEnabled) {
        e.preventDefault()
        triggerImageUpload()
      }
      return
    }

    let actionKey: string | undefined
    if (e.key === 'e' || e.key === 'E') {
      actionKey = e.shiftKey ? 'codeblock' : 'code'
    } else if ((e.key === '>' || e.key === '.') && e.shiftKey) {
      actionKey = 'blockquote'
    } else if (!e.shiftKey) {
      actionKey = KEY_MAP[e.key.toLowerCase()]
    }

    if (actionKey === undefined) return
    e.preventDefault()
    applyAction(actionKey)
  }

  const content = (
    <div
      className={
        isFullscreen ? 'fixed inset-0 z-50 flex flex-col bg-paper p-4 overflow-hidden' : ''
      }
    >
      {enableAssets && !isFullscreen && (
        <div className="mb-4">
          <FileStrip
            filePath={filePath}
            body={value}
            onBodyChange={onChange}
            onInsertAtCursor={insertAtCursor}
            disabled={disabled}
            refreshToken={fileRefreshToken}
          />
        </div>
      )}

      <div className="flex lg:hidden mb-4 border-b border-border">
        <button
          type="button"
          onClick={() => setMobileTab('edit')}
          className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
            mobileTab === 'edit'
              ? 'border-accent text-accent'
              : 'border-transparent text-muted hover:text-ink'
          }`}
        >
          Edit
        </button>
        <button
          type="button"
          onClick={() => setMobileTab('preview')}
          className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
            mobileTab === 'preview'
              ? 'border-accent text-accent'
              : 'border-transparent text-muted hover:text-ink'
          }`}
        >
          Preview
        </button>
      </div>

      <div className={mobileTab === 'preview' ? 'hidden lg:block' : ''}>
        <MarkdownToolbar
          textareaRef={textareaRef}
          value={value}
          onChange={onChange}
          disabled={disabled}
          {...(onSave !== undefined && { onSave })}
          saving={saving}
          canSave={canSave}
          isFullscreen={isFullscreen}
          onToggleFullscreen={() => setIsFullscreen((f) => !f)}
          {...(enableAssets && {
            onImageClick: imageUploadEnabled ? triggerImageUpload : undefined,
            imageUploading,
            ...(imageDisabledReason !== undefined && { imageDisabledReason }),
          })}
        />
        {enableAssets && <input {...imageInputProps} />}
      </div>

      <div
        className={`grid grid-cols-1 lg:grid-cols-[1fr_2.5rem_1fr] gap-4 ${
          isFullscreen ? 'flex-1 min-h-0' : ''
        }`}
      >
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          style={isFullscreen ? undefined : { height: editorHeight }}
          className={`w-full overflow-y-auto p-4 bg-paper-warm border border-border rounded-lg
                   font-mono text-sm leading-relaxed text-ink resize-none
                   focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/20
                   disabled:opacity-50 ${mobileTab === 'preview' ? 'hidden lg:block' : ''} ${isFullscreen ? 'h-full' : ''}`}
          spellCheck={false}
        />

        <div className="hidden lg:flex flex-col items-center justify-center gap-2">
          <button
            type="button"
            onClick={syncEditorToPreview}
            disabled={disabled}
            title="Go to editor position in preview"
            aria-label="Go to editor position in preview"
            className="p-1.5 text-muted hover:text-ink hover:bg-paper-warm rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <ChevronRight size={16} />
          </button>
          <button
            type="button"
            onClick={syncPreviewToEditor}
            disabled={disabled}
            title="Go to preview position in editor"
            aria-label="Go to preview position in editor"
            className="p-1.5 text-muted hover:text-ink hover:bg-paper-warm rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <ChevronLeft size={16} />
          </button>
        </div>

        <div
          ref={previewRef}
          style={isFullscreen ? undefined : { height: editorHeight }}
          className={`relative p-6 bg-paper border border-border rounded-lg overflow-y-auto ${
            mobileTab === 'edit' ? 'hidden lg:block' : ''
          } ${isFullscreen ? 'h-full' : ''}`}
        >
          {previewError ? (
            <p className="text-sm text-red-600 dark:text-red-400 italic">Preview unavailable</p>
          ) : hasContent ? (
            <div
              className="prose max-w-none"
              // nosemgrep: typescript.react.security.audit.react-dangerouslysetinnerhtml
              // Preview HTML is rendered and sanitized server-side.
              dangerouslySetInnerHTML={{ __html: html }}
            />
          ) : (
            <div className="flex flex-col items-center justify-center h-full min-h-[200px] border-2 border-dashed border-border/50 rounded-lg bg-paper-warm/30">
              <Eye size={32} className="text-muted/40 mb-3" />
              <p className="text-sm text-muted/60">Start typing to see a live preview</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )

  // In fullscreen, portal to document.body so the `fixed inset-0` overlay
  // anchors to the viewport. Hosts wrap the editor in a transformed
  // `animate-fade-in` element, which would otherwise become the containing
  // block and confine the overlay to the host's content column.
  return isFullscreen ? createPortal(content, document.body) : content
}
