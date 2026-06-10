import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react'
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
  lineStartIndex,
  pageTarget,
  smartHomeTarget,
} from './textareaKeys'
import { useScrollSync } from '@/hooks/useScrollSync'
import { useMarkdownPreview } from '@/hooks/useMarkdownPreview'
import FileStrip from './FileStrip'
import { useFileUpload } from './useFileUpload'

const KEY_MAP: Record<string, string> = { b: 'bold', i: 'italic', e: 'code', h: 'heading', k: 'link', u: 'underline' }
const SHIFT_KEY_MAP: Record<string, string> = {
  e: 'codeblock', '>': 'blockquote', '.': 'blockquote',
  x: 'strikethrough', '*': 'bulletList', '&': 'orderedList', f: 'footnote',
}
const NAVIGATION_KEYS = new Set(['Home', 'End', 'PageUp', 'PageDown'])

/**
 * Move the focused textarea's caret/selection by `steps` of `granularity` using
 * the browser's native `Selection.modify`. This drives Home/End ('lineboundary')
 * and PageUp/PageDown ('line') through the real layout engine, so word-wrap and
 * caret affinity are always correct — it is the same machinery behind macOS
 * Cmd+Left/Right and visual line up/down. Returns false when `Selection.modify`
 * is unavailable (e.g. jsdom under test), letting callers fall back to
 * logical-line movement.
 */
function moveByModify(
  granularity: 'lineboundary' | 'line',
  direction: 'backward' | 'forward',
  extend: boolean,
  steps: number,
): boolean {
  const selection = window.getSelection()
  if (!selection) return false
  // `Selection.modify` is non-standard; the DOM lib types mark it required, but
  // it is absent in some environments (jsdom under test), so read it through an
  // optional-typed view and fall back when missing.
  const modify = (selection as { modify?: Selection['modify'] }).modify
  if (!modify) return false
  try {
    for (let i = 0; i < steps; i++) {
      modify.call(selection, extend ? 'extend' : 'move', direction, granularity)
    }
  } catch {
    return false
  }
  return true
}

/** Offset of the moving end of the textarea's current selection. */
function activeOffset(textarea: HTMLTextAreaElement): number {
  const { selectionStart, selectionEnd, selectionDirection } = textarea
  if (selectionStart === selectionEnd) return selectionStart
  return selectionDirection === 'backward' ? selectionStart : selectionEnd
}

/** Apply a computed caret target, collapsing or extending the selection. */
function applyCaretTarget(textarea: HTMLTextAreaElement, target: number, extend: boolean): void {
  if (!extend) {
    textarea.setSelectionRange(target, target)
    return
  }
  const { selectionStart, selectionEnd, selectionDirection } = textarea
  const anchor =
    selectionStart === selectionEnd
      ? selectionStart
      : selectionDirection === 'backward'
        ? selectionEnd
        : selectionStart
  textarea.setSelectionRange(
    Math.min(anchor, target),
    Math.max(anchor, target),
    target < anchor ? 'backward' : 'forward',
  )
}

/** Effective line height of the textarea in CSS pixels. */
function textareaLineHeight(textarea: HTMLTextAreaElement): number {
  const style = window.getComputedStyle(textarea)
  const lineHeight = parseFloat(style.lineHeight)
  if (Number.isNaN(lineHeight) || lineHeight <= 0) {
    return parseFloat(style.fontSize) * 1.2 || 16
  }
  return lineHeight
}

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

  const handleToggleFullscreen = useCallback(() => setIsFullscreen((f) => !f), [])

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

  function applyNavigation(key: string, shiftKey: boolean) {
    const textarea = textareaRef.current
    if (!textarea) return

    if (key === 'Home' || key === 'End') {
      const direction = key === 'Home' ? 'backward' : 'forward'
      const caretBefore = textarea.selectionStart
      if (moveByModify('lineboundary', direction, shiftKey, 1)) {
        // Smart Home on the FIRST visual row only: toggle first-non-whitespace
        // ↔ column zero. On wrapped continuation rows the native move already
        // landed at the visual row start, so leave it.
        if (key === 'Home' && !shiftKey) {
          const lineStart = lineStartIndex(value, caretBefore)
          if (textarea.selectionStart === lineStart) {
            const target = smartHomeTarget(value, caretBefore)
            if (target !== textarea.selectionStart) textarea.setSelectionRange(target, target)
          }
        }
        return
      }
      // Fallback (no live layout, e.g. jsdom): logical line start/end.
      const active = activeOffset(textarea)
      const target = key === 'Home' ? smartHomeTarget(value, active) : lineEndTarget(value, active)
      applyCaretTarget(textarea, target, shiftKey)
      return
    }

    // PageUp / PageDown: move a viewport's worth of visual lines.
    const direction = key === 'PageUp' ? 'backward' : 'forward'
    const visibleRows = Math.max(
      1,
      Math.floor(textarea.clientHeight / textareaLineHeight(textarea)) - 1,
    )
    if (moveByModify('line', direction, shiftKey, visibleRows)) {
      // Scroll a page so the caret keeps its on-screen row.
      textarea.scrollTop = Math.max(
        0,
        Math.min(
          textarea.scrollHeight - textarea.clientHeight,
          direction === 'backward'
            ? textarea.scrollTop - textarea.clientHeight
            : textarea.scrollTop + textarea.clientHeight,
        ),
      )
      return
    }
    // Fallback: logical page move.
    const active = activeOffset(textarea)
    const target = pageTarget(value, active, visibleRows, direction === 'backward' ? 'up' : 'down')
    applyCaretTarget(textarea, target, shiftKey)
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    const isMod = e.metaKey || e.ctrlKey

    if (e.key === 'Tab' && !isMod && !e.altKey) {
      e.preventDefault()
      applyTab(e.shiftKey)
      return
    }

    if (!isMod && !e.altKey && NAVIGATION_KEYS.has(e.key)) {
      e.preventDefault()
      applyNavigation(e.key, e.shiftKey)
      return
    }

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

    const actionKey = e.shiftKey
      ? SHIFT_KEY_MAP[e.key.toLowerCase()]
      : KEY_MAP[e.key.toLowerCase()]

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
          onToggleFullscreen={handleToggleFullscreen}
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
