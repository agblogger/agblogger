import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Save, ArrowLeft, Eye } from 'lucide-react'
import { useSWRConfig } from 'swr'
import { formatLocalDate } from '@/utils/date'

import { fetchPostForEdit, createPost, updatePost } from '@/api/posts'
import AlertBanner from '@/components/AlertBanner'
import { HTTPError } from '@/api/client'
import { parseErrorDetail } from '@/api/parseError'
import { useSocialAccounts } from '@/hooks/useSocialAccounts'
import { postUrl } from '@/utils/postUrl'
import { buildEditorDraftStorageKey, useEditorAutoSave } from '@/hooks/useEditorAutoSave'
import type { DraftData } from '@/hooks/useEditorAutoSave'
import { useRequireAdmin } from '@/hooks/useRequireAdmin'
import CrossPostDialog from '@/components/crosspost/CrossPostDialog'
import PlatformIcon from '@/components/crosspost/PlatformIcon'
import LabelInput from '@/components/editor/LabelInput'
import MarkdownEditor from '@/components/editor/MarkdownEditor'

export default function EditorPage() {
  const { '*': filePath } = useParams()
  const navigate = useNavigate()
  const isNew = filePath === undefined || filePath === 'new'
  const { user, isReady } = useRequireAdmin()
  const { mutate } = useSWRConfig()

  const [title, setTitle] = useState('')
  const [subtitle, setSubtitle] = useState('')
  const [body, setBody] = useState('')
  const [labels, setLabels] = useState<string[]>([])
  const [isDraft, setIsDraft] = useState(isNew)
  const [loadedAuthor, setLoadedAuthor] = useState<string | null>(null)
  const [createdAt, setCreatedAt] = useState<string | null>(null)
  const [modifiedAt, setModifiedAt] = useState<string | null>(null)
  const [loading, setLoading] = useState(!isNew)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { data: accounts = [], error: socialAccountsErr } = useSocialAccounts()
  const socialAccountsError = socialAccountsErr ? 'Failed to load connected social accounts. Please try again.' : null
  const [selectedPlatforms, setSelectedPlatforms] = useState<string[]>([])
  const [showCrossPostDialog, setShowCrossPostDialog] = useState(false)
  const [savedFilePath, setSavedFilePath] = useState<string | null>(null)
  const [effectiveFilePath, setEffectiveFilePath] = useState<string | null>(
    isNew ? null : filePath,
  )

  useEffect(() => {
    if (isNew) {
      setIsDraft(true)
    }
  }, [isNew])

  const draftOwnerId = user?.id ?? 0
  const autoSaveKey = buildEditorDraftStorageKey(draftOwnerId, isNew ? undefined : filePath)
  const currentState = useMemo<DraftData>(
    () => ({ title, subtitle, body, labels, isDraft }),
    [title, subtitle, body, labels, isDraft],
  )

  const handleRestore = useCallback((draft: DraftData) => {
    setTitle(draft.title)
    setSubtitle(draft.subtitle)
    setBody(draft.body)
    setLabels(draft.labels)
    setIsDraft(draft.isDraft)
  }, [])

  const { isDirty, draftAvailable, draftSavedAt, restoreDraft, discardDraft, markSaved } =
    useEditorAutoSave({
      key: autoSaveKey,
      currentState,
      onRestore: handleRestore,
      enabled: Boolean(user) && (isNew || !loading),
    })

  useEffect(() => {
    if (!isNew && filePath) {
      setLoading(true)
      fetchPostForEdit(filePath)
        .then((data) => {
          setTitle(data.title)
          setSubtitle(data.subtitle ?? '')
          setBody(data.body)
          setLabels(data.labels)
          setIsDraft(data.is_draft)
          setLoadedAuthor(data.author)
          setCreatedAt(data.created_at)
          setModifiedAt(data.modified_at)
        })
        .catch((err: unknown) => {
          if (err instanceof HTTPError && err.response.status === 404) {
            setError('Post not found')
          } else if (err instanceof HTTPError && err.response.status === 401) {
            setError('Session expired. Please log in again.')
          } else {
            setError('Failed to load post')
          }
        })
        .finally(() => setLoading(false))
    }
  }, [filePath, isNew])

  const author = isNew ? (user?.display_name ?? user?.username ?? null) : loadedAuthor

  async function handleSave() {
    setSaving(true)
    setError(null)
    try {
      let result
      if (isNew) {
        result = await createPost({ title, subtitle: subtitle.trim() || null, body, labels, is_draft: isDraft })
      } else {
        result = await updatePost(filePath, { title, subtitle: subtitle.trim() || null, body, labels, is_draft: isDraft })
      }
      const resultSlug = postUrl(result.file_path).replace('/post/', '')
      await mutate(['post', resultSlug, draftOwnerId], result, { revalidate: false })
      await mutate(
        (key) =>
          Array.isArray(key) &&
          key[0] === 'labelPosts' &&
          key[2] === draftOwnerId,
        undefined,
        { revalidate: true },
      )
      markSaved()
      setSavedFilePath(result.file_path)
      setEffectiveFilePath(result.file_path)
      setCreatedAt(result.created_at)
      setModifiedAt(result.modified_at)
      if (isNew) {
        void navigate(`/editor/${result.file_path}`, { replace: true })
      }
      if (!isDraft && selectedPlatforms.length > 0) {
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

  if (!isReady) {
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
                void navigate(postUrl(effectiveFilePath))
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
        <AlertBanner variant="error" className="mb-4">{error}</AlertBanner>
      )}

      {socialAccountsError !== null && (
        <AlertBanner variant="error" className="mb-4">{socialAccountsError}</AlertBanner>
      )}

      {draftAvailable && draftSavedAt !== null && (
        <div className="mb-4 flex items-center justify-between text-sm bg-sky-50 dark:bg-sky-950/30 border border-sky-200 dark:border-sky-800/40 rounded-lg px-4 py-3">
          <span className="text-sky-800 dark:text-sky-300">
            You have unsaved changes from{' '}
            {formatLocalDate(draftSavedAt, { dateStyle: 'medium', timeStyle: 'short' })}
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
          <input
            id="subtitle"
            type="text"
            value={subtitle}
            onChange={(e) => setSubtitle(e.target.value)}
            disabled={saving}
            maxLength={500}
            placeholder="Subtitle"
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
            <button
              type="button"
              role="switch"
              aria-checked={isDraft}
              aria-label="Draft"
              onClick={() => setIsDraft((d) => !d)}
              disabled={saving}
              className={`inline-flex items-center gap-2.5 px-3 py-2 rounded-lg border transition-colors disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50 ${
                isDraft
                  ? 'bg-amber-50 dark:bg-amber-900/20 border-amber-300 dark:border-amber-700'
                  : 'bg-paper-warm border-border'
              }`}
            >
              <div
                className={`relative w-8 h-[18px] rounded-full flex-shrink-0 transition-colors ${
                  isDraft ? 'bg-amber-400 dark:bg-amber-500' : 'bg-border-dark'
                }`}
              >
                <div
                  className={`absolute top-0.5 w-3.5 h-3.5 bg-white rounded-full shadow-sm transition-transform ${
                    isDraft ? 'translate-x-[14px]' : 'translate-x-0.5'
                  }`}
                />
              </div>
              <div>
                <div
                  className={`text-[10px] font-mono font-semibold uppercase tracking-widest leading-tight ${
                    isDraft ? 'text-amber-800 dark:text-amber-300' : 'text-muted'
                  }`}
                >
                  DRAFT
                </div>
                <div
                  className={`text-[11px] leading-tight mt-0.5 ${
                    isDraft ? 'text-amber-700 dark:text-amber-400' : 'text-muted'
                  }`}
                >
                  {isDraft ? 'Not publicly visible' : 'Publicly visible'}
                </div>
              </div>
            </button>

            {author !== null && (
              <span className="text-sm text-muted">
                Author: <span className="text-ink">{author}</span>
              </span>
            )}
          </div>

          {!isNew && (createdAt !== null || modifiedAt !== null) && (
            <div className="flex items-center gap-4 text-xs text-muted">
              {createdAt !== null && <span>Created {formatLocalDate(createdAt, { dateStyle: 'medium', timeStyle: 'medium' })}</span>}
              {modifiedAt !== null && <span>Modified {formatLocalDate(modifiedAt, { dateStyle: 'medium', timeStyle: 'medium' })}</span>}
            </div>
          )}
        </div>

        {accounts.length > 0 && (
          <div className="flex items-center gap-4 flex-wrap">
            <span className="text-xs font-medium text-muted">Cross-post after saving:</span>
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
                  disabled={saving || isDraft}
                  className="rounded border-border text-accent focus:ring-accent/20"
                />
                <PlatformIcon platform={acct.platform} size={14} />
                <span className={`text-sm ${isDraft ? 'text-muted' : 'text-ink'}`}>
                  {acct.account_name}
                </span>
              </label>
            ))}
            {isDraft && (
              <span className="text-xs text-muted">
                Publish the post to enable cross-posting after saving.
              </span>
            )}
          </div>
        )}
      </div>

      <MarkdownEditor
        value={body}
        onChange={setBody}
        disabled={saving}
        onSave={() => void handleSave()}
        saving={saving}
        canSave={title.trim().length > 0}
        filePath={effectiveFilePath}
        enableAssets
        assetDisabledReason="Save post first to add images"
      />

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
