import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { ChevronRight, ChevronLeft, Eye } from 'lucide-react'

import MarkdownToolbar from './MarkdownToolbar'
import { actions as toolbarActions } from './toolbarActions'
import { wrapSelection } from './wrapSelection'
import { useScrollSync } from '@/hooks/useScrollSync'
import { useMarkdownPreview } from '@/hooks/useMarkdownPreview'

const KEY_MAP: Record<string, string> = { b: 'bold', i: 'italic', h: 'heading', k: 'link' }

export interface MarkdownEditorProps {
  value: string
  onChange: (value: string) => void
  disabled?: boolean
  onSave?: () => void
  saving?: boolean
  canSave?: boolean
  filePath?: string | null
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
    return () => window.removeEventListener('keydown', onKey)
  }, [isFullscreen])

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

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    const isMod = e.metaKey || e.ctrlKey
    if (!isMod) return

    if ((e.key === 's' || e.key === 'S') && !e.shiftKey) {
      if (onSave !== undefined && saveAllowed) {
        e.preventDefault()
        onSave()
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

  return (
    <div
      className={
        isFullscreen ? 'fixed inset-0 z-50 flex flex-col bg-paper p-4 overflow-hidden' : ''
      }
    >
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
        />
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
}
