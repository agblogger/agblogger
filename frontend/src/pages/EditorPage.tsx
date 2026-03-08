import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Save, ArrowLeft, Eye } from 'lucide-react'
import { format, parseISO } from 'date-fns'

import { fetchPostForEdit, createPost, updatePost } from '@/api/posts'
import { fetchSocialAccounts } from '@/api/crosspost'
import type { SocialAccount } from '@/api/crosspost'
import { HTTPError } from '@/api/client'
import { parseErrorDetail } from '@/api/parseError'
import api from '@/api/client'
import { useCodeBlockEnhance } from '@/hooks/useCodeBlockEnhance'
import { useEditorAutoSave } from '@/hooks/useEditorAutoSave'
import type { DraftData } from '@/hooks/useEditorAutoSave'
import { useRenderedHtml } from '@/hooks/useKatex'
import { useAuthStore } from '@/stores/authStore'
import CrossPostDialog from '@/components/crosspost/CrossPostDialog'
import PlatformIcon from '@/components/crosspost/PlatformIcon'
import LabelInput from '@/components/editor/LabelInput'
import MarkdownToolbar from '@/components/editor/MarkdownToolbar'
import { actions as toolbarActions } from '@/components/editor/toolbarActions'
import { wrapSelection } from '@/components/editor/wrapSelection'
import FileStrip from '@/components/editor/FileStrip'

export default function EditorPage() {
  const { '*': filePath } = useParams()
  const navigate = useNavigate()
  const isNew = filePath === undefined || filePath === 'new'
  const user = useAuthStore((s) => s.user)
  const isInitialized = useAuthStore((s) => s.isInitialized)

  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [labels, setLabels] = useState<string[]>([])
  const [isDraft, setIsDraft] = useState(false)
  const [author, setAuthor] = useState<string | null>(null)
  const [createdAt, setCreatedAt] = useState<string | null>(null)
  const [modifiedAt, setModifiedAt] = useState<string | null>(null)
  const [loading, setLoading] = useState(!isNew)
  const [saving, setSaving] = useState(false)
  const [preview, setPreview] = useState<string | null>(null)
  const [previewError, setPreviewError] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const renderedPreview = useRenderedHtml(preview)
  const previewRequestRef = useRef(0)
  const previewRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const [accounts, setAccounts] = useState<SocialAccount[]>([])
  const [selectedPlatforms, setSelectedPlatforms] = useState<string[]>([])
  const [showCrossPostDialog, setShowCrossPostDialog] = useState(false)
  const [mobileTab, setMobileTab] = useState<'edit' | 'preview'>('edit')
  const [savedFilePath, setSavedFilePath] = useState<string | null>(null)
  const [effectiveFilePath, setEffectiveFilePath] = useState<string | null>(
    isNew ? null : filePath ?? null,
  )
  useCodeBlockEnhance(previewRef, renderedPreview)

  const autoSaveKey = isNew ? 'agblogger:draft:new' : `agblogger:draft:${filePath}`
  const currentState = useMemo<DraftData>(
    () => ({ title, body, labels, isDraft }),
    [title, body, labels, isDraft],
  )

  const handleRestore = useCallback((draft: DraftData) => {
    setTitle(draft.title)
    setBody(draft.body)
    setLabels(draft.labels)
    setIsDraft(draft.isDraft)
  }, [])

  const { isDirty, draftAvailable, draftSavedAt, restoreDraft, discardDraft, markSaved } =
    useEditorAutoSave({
      key: autoSaveKey,
      currentState,
      onRestore: handleRestore,
      enabled: isNew || !loading,
    })

  useEffect(() => {
    if (isInitialized && !user) {
      void navigate('/login', { replace: true })
    }
  }, [user, isInitialized, navigate])

  useEffect(() => {
    if (!isNew && filePath) {
      setLoading(true)
      fetchPostForEdit(filePath)
        .then((data) => {
          setTitle(data.title)
          setBody(data.body)
          setLabels(data.labels)
          setIsDraft(data.is_draft)
          setAuthor(data.author)
          setCreatedAt(data.created_at)
          setModifiedAt(data.modified_at)
        })
        .catch((err: unknown) => {
          if (err instanceof HTTPError && err.response.status === 404) {
            setError('Post not found')
          } else {
            setError('Failed to load post')
          }
        })
        .finally(() => setLoading(false))
    }
  }, [filePath, isNew])

  useEffect(() => {
    if (isNew) {
      setAuthor(user?.display_name ?? user?.username ?? null)
    }
  }, [isNew, user?.display_name, user?.username])

  useEffect(() => {
    if (user) {
      fetchSocialAccounts()
        .then(setAccounts)
        .catch((err: unknown) => {
          console.warn('Failed to load social accounts', err)
        })
    }
  }, [user])

  useEffect(() => {
    if (body.length === 0) return
    const requestId = ++previewRequestRef.current
    const timer = setTimeout(async () => {
      try {
        const payload: { markdown: string; file_path?: string } = { markdown: body }
        if (!isNew && filePath) {
          payload.file_path = filePath
        }
        const resp = await api
          .post('render/preview', { json: payload })
          .json<{ html: string }>()
        if (previewRequestRef.current === requestId) {
          setPreview(resp.html)
          setPreviewError(false)
        }
      } catch {
        if (previewRequestRef.current === requestId) {
          setPreviewError(true)
        }
      }
    }, 500)
    return () => clearTimeout(timer)
  }, [body, isNew, filePath])

  async function handleSave() {
    setSaving(true)
    setError(null)
    try {
      let result
      if (isNew) {
        result = await createPost({ title, body, labels, is_draft: isDraft })
      } else {
        result = await updatePost(filePath, { title, body, labels, is_draft: isDraft })
      }
      markSaved()
      setSavedFilePath(result.file_path)
      setEffectiveFilePath(result.file_path)
      if (isNew) {
        void navigate(`/editor/${result.file_path}`, { replace: true })
      }
      if (selectedPlatforms.length > 0) {
        setShowCrossPostDialog(true)
      }
    } catch (err) {
      if (err instanceof HTTPError) {
        const status = err.response.status
        if (status === 401) {
          setError('Session expired. Please log in again.')
        } else if (status === 409) {
          setError('Conflict: this post was modified elsewhere.')
        } else if (status === 404) {
          setError('Post not found. It may have been deleted.')
        } else if (status === 422) {
          const message = await parseErrorDetail(
            err.response,
            'Validation error. Check your input.',
          )
          setError(message)
        } else {
          setError('Failed to save post. Please try again.')
        }
      } else {
        setError('Failed to save post. The server may be unavailable.')
      }
    } finally {
      setSaving(false)
    }
  }

  function handleCrossPostClose() {
    setShowCrossPostDialog(false)
  }

  function handleInsertAtCursor(text: string) {
    const textarea = textareaRef.current
    if (!textarea) return
    const pos = textarea.selectionStart
    const before = body.slice(0, pos)
    const after = body.slice(pos)
    setBody(before + text + after)
  }

  function formatDate(iso: string): string {
    try {
      const parsed = parseISO(iso.replace(' ', 'T').replace(/\+(\d{2})$/, '+$1:00'))
      return format(parsed, 'MMM d, yyyy, HH:mm')
    } catch {
      return iso.split('.')[0] ?? iso
    }
  }

  function handleEditorKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    const isMod = e.metaKey || e.ctrlKey
    if (!isMod) return

    const keyMap: Record<string, string> = {
      b: 'bold',
      i: 'italic',
      h: 'heading',
      k: 'link',
    }

    let actionKey: string | undefined
    if (e.key === 'e' || e.key === 'E') {
      actionKey = e.shiftKey ? 'codeblock' : 'code'
    } else {
      actionKey = keyMap[e.key.toLowerCase()]
    }

    if (actionKey === undefined) return
    const action = toolbarActions[actionKey]
    if (action === undefined) return

    e.preventDefault()
    const textarea = textareaRef.current
    if (!textarea) return

    const { newValue, cursorStart, cursorEnd } = wrapSelection(
      body,
      textarea.selectionStart,
      textarea.selectionEnd,
      action,
    )
    setBody(newValue)
    requestAnimationFrame(() => {
      textarea.focus()
      textarea.setSelectionRange(cursorStart, cursorEnd)
    })
  }

  if (!isInitialized || !user) {
    return null
  }

  if (loading) {
    return (
      <div className="animate-fade-in flex items-center justify-center py-20">
        <span className="text-muted text-sm">Loading...</span>
      </div>
    )
  }

  if (!isNew && error !== null) {
    return (
      <div className="animate-fade-in text-center py-24">
        <p className="font-display text-3xl text-muted italic">
          {error === 'Post not found' ? '404' : 'Error'}
        </p>
        <p className="text-sm text-muted mt-2">{error}</p>
        <button
          onClick={() => void navigate(-1)}
          className="text-accent text-sm hover:underline mt-4 inline-block"
        >
          Go back
        </button>
      </div>
    )
  }

  return (
    <div className="animate-fade-in">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <button
            onClick={() => void navigate(-1)}
            className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink transition-colors"
          >
            <ArrowLeft size={14} />
            Back
          </button>
          {isDirty && <span className="text-muted text-sm">*</span>}
        </div>

        <div className="flex items-center gap-2">
          {effectiveFilePath !== null && (
            <button
              onClick={() => {
                if (isDirty && !window.confirm('You have unsaved changes. Leave without saving?'))
                  return
                void navigate(`/post/${effectiveFilePath}`)
              }}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium
                       text-muted border border-border rounded-lg
                       hover:text-ink hover:bg-paper-warm
                       disabled:opacity-50 transition-colors"
            >
              <Eye size={14} />
              View post
            </button>
          )}
          <button
            onClick={() => void handleSave()}
            disabled={saving || !title.trim()}
            className="flex items-center gap-1.5 px-4 py-1.5 text-sm font-medium
                     bg-accent text-white rounded-lg hover:bg-accent-light disabled:opacity-50 transition-colors"
          >
            <Save size={14} />
            {saving ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>

      {error !== null && (
        <div className="mb-4 text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800/40 rounded-lg px-4 py-3">
          {error}
        </div>
      )}

      {draftAvailable && draftSavedAt !== null && (
        <div className="mb-4 flex items-center justify-between text-sm bg-sky-50 dark:bg-sky-950/30 border border-sky-200 dark:border-sky-800/40 rounded-lg px-4 py-3">
          <span className="text-sky-800 dark:text-sky-300">
            You have unsaved changes from{' '}
            {format(parseISO(draftSavedAt), 'MMM d, h:mm a')}
          </span>
          <span className="flex gap-2">
            <button
              onClick={restoreDraft}
              className="font-medium text-sky-700 dark:text-sky-400 hover:text-sky-900 dark:hover:text-sky-300 hover:underline"
            >
              Restore
            </button>
            <button
              onClick={discardDraft}
              className="font-medium text-sky-500 dark:text-sky-400 hover:text-sky-700 dark:hover:text-sky-400 hover:underline"
            >
              Discard
            </button>
          </span>
        </div>
      )}

      <div className="mb-4 space-y-3 p-4 bg-paper border border-border rounded-lg">
        <div>
          <div className="flex items-center justify-between mb-1">
            <label htmlFor="title" className="block text-xs font-medium text-muted">
              Title *
            </label>
            <span className="text-xs text-muted">{title.length} / 500</span>
          </div>
          <input
            id="title"
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            disabled={saving}
            maxLength={500}
            placeholder="Post title"
            className="w-full px-3 py-2 bg-paper-warm border border-border rounded-lg
                     text-ink text-sm
                     focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/20
                     disabled:opacity-50"
          />
        </div>

        <div>
          <label className="block text-xs font-medium text-muted mb-1">Labels</label>
          <LabelInput value={labels} onChange={setLabels} disabled={saving} />
        </div>

        <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-1">
          <div className="flex items-center gap-6">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={isDraft}
                onChange={(e) => setIsDraft(e.target.checked)}
                disabled={saving}
                className="rounded border-border text-accent focus:ring-accent/20"
              />
              <span className="text-sm text-ink">Draft</span>
            </label>

            {author !== null && (
              <span className="text-sm text-muted">
                Author: <span className="text-ink">{author}</span>
              </span>
            )}
          </div>

          {!isNew && (createdAt !== null || modifiedAt !== null) && (
            <div className="flex items-center gap-4 text-xs text-muted">
              {createdAt !== null && <span>Created {formatDate(createdAt)}</span>}
              {modifiedAt !== null && <span>Modified {formatDate(modifiedAt)}</span>}
            </div>
          )}
        </div>

        {accounts.length > 0 && (
          <div className="flex items-center gap-4 flex-wrap">
            <span className="text-xs font-medium text-muted">Share after saving:</span>
            {accounts.map((acct) => (
              <label key={acct.id} className="flex items-center gap-1.5 cursor-pointer">
                <input
                  type="checkbox"
                  checked={selectedPlatforms.includes(acct.platform)}
                  onChange={(e) => {
                    if (e.target.checked) {
                      setSelectedPlatforms((prev) => [...prev, acct.platform])
                    } else {
                      setSelectedPlatforms((prev) => prev.filter((p) => p !== acct.platform))
                    }
                  }}
                  disabled={saving}
                  className="rounded border-border text-accent focus:ring-accent/20"
                />
                <PlatformIcon platform={acct.platform} size={14} />
                <span className="text-sm text-ink">{acct.account_name}</span>
              </label>
            ))}
          </div>
        )}
      </div>

      <div className="mb-4">
        <FileStrip
          filePath={effectiveFilePath}
          body={body}
          onBodyChange={setBody}
          onInsertAtCursor={handleInsertAtCursor}
          disabled={saving}
        />
      </div>

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

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4" style={{ minHeight: '60vh' }}>
        <div className={mobileTab === 'preview' ? 'hidden lg:block' : ''}>
          <MarkdownToolbar
            textareaRef={textareaRef}
            value={body}
            onChange={setBody}
            disabled={saving}
          />
          <textarea
            ref={textareaRef}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            onKeyDown={handleEditorKeyDown}
            disabled={saving}
            className="w-full h-full min-h-[60vh] p-4 bg-paper-warm border border-border rounded-lg
                     font-mono text-sm leading-relaxed text-ink resize-none
                     focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/20
                     disabled:opacity-50"
            spellCheck={false}
          />
        </div>

        <div className={`p-6 bg-paper border border-border rounded-lg overflow-y-auto ${mobileTab === 'edit' ? 'hidden lg:block' : ''}`}>
          {previewError ? (
            <p className="text-sm text-red-600 dark:text-red-400 italic">Preview unavailable</p>
          ) : preview !== null ? (
            <div
              ref={previewRef}
              className="prose max-w-none"
              dangerouslySetInnerHTML={{ __html: renderedPreview }}
            />
          ) : (
            <div className="flex flex-col items-center justify-center h-full min-h-[200px] border-2 border-dashed border-border/50 rounded-lg bg-paper-warm/30">
              <Eye size={32} className="text-muted/40 mb-3" />
              <p className="text-sm text-muted/60">Start typing to see a live preview</p>
            </div>
          )}
        </div>
      </div>

      {showCrossPostDialog && savedFilePath !== null && (
        <CrossPostDialog
          open={showCrossPostDialog}
          onClose={handleCrossPostClose}
          accounts={accounts}
          postPath={savedFilePath}
          postTitle={title}
          postExcerpt=""
          postLabels={labels}
          initialPlatforms={selectedPlatforms}
        />
      )}
    </div>
  )
}
