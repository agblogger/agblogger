import { useEffect, useRef, useState } from 'react'
import {
  FileText,
  ArrowUp,
  ArrowDown,
  Plus,
  Trash2,
  ChevronDown,
  ChevronRight,
  Save,
} from 'lucide-react'

import { HTTPError } from '@/api/client'
import api from '@/api/client'
import type { AdminPageConfig } from '@/api/client'
import {
  createAdminPage,
  updateAdminPage,
  updateAdminPageOrder,
  deleteAdminPage,
} from '@/api/admin'
import { useRenderedHtml } from '@/hooks/useKatex'
import { useSiteStore } from '@/stores/siteStore'

const BUILTIN_PAGE_IDS = new Set(['timeline', 'labels'])

function PagePreview({ markdown }: { markdown: string }) {
  const [html, setHtml] = useState<string | null>(null)
  const [previewError, setPreviewError] = useState(false)
  const requestRef = useRef(0)
  const hasContent = markdown.trim().length > 0

  useEffect(() => {
    if (!hasContent) return
    const requestId = ++requestRef.current
    const timer = setTimeout(async () => {
      try {
        const resp = await api
          .post('render/preview', { json: { markdown } })
          .json<{ html: string }>()
        if (requestRef.current === requestId) {
          setHtml(resp.html)
          setPreviewError(false)
        }
      } catch (err) {
        console.warn('Page preview render failed:', err)
        if (requestRef.current === requestId) {
          setPreviewError(true)
        }
      }
    }, 500)
    return () => clearTimeout(timer)
  }, [markdown, hasContent])

  const rendered = useRenderedHtml(hasContent ? html : null)

  if (previewError) {
    return <p className="text-sm text-red-600 dark:text-red-400 italic">Preview unavailable</p>
  }

  if (!rendered) {
    return <p className="text-sm text-muted italic">Preview will appear here...</p>
  }

  // nosemgrep: typescript.react.security.audit.react-dangerouslysetinnerhtml
  // Page HTML is rendered and sanitized server-side by the backend rendering pipeline.
  return <div className="prose max-w-none" dangerouslySetInnerHTML={{ __html: rendered }} />
}

interface PagesSectionProps {
  initialPages: AdminPageConfig[]
  busy: boolean
  onSaving: (saving: boolean) => void
  onPagesChange: (pages: AdminPageConfig[]) => void
}

export default function PagesSection({
  initialPages,
  busy,
  onSaving,
  onPagesChange,
}: PagesSectionProps) {
  const [pages, setPages] = useState<AdminPageConfig[]>(initialPages)
  const [pagesError, setPagesError] = useState<string | null>(null)
  const [pagesSuccess, setPagesSuccess] = useState<string | null>(null)
  const [savingOrder, setSavingOrder] = useState(false)
  const [orderDirty, setOrderDirty] = useState(false)

  const [showAddForm, setShowAddForm] = useState(false)
  const [newPageId, setNewPageId] = useState('')
  const [newPageTitle, setNewPageTitle] = useState('')
  const [creatingPage, setCreatingPage] = useState(false)

  const [expandedPageId, setExpandedPageId] = useState<string | null>(null)
  const [editTitle, setEditTitle] = useState('')
  const [editContent, setEditContent] = useState('')
  const [savingPage, setSavingPage] = useState(false)
  const [deletingPage, setDeletingPage] = useState(false)
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null)
  const [pageEditError, setPageEditError] = useState<string | null>(null)
  const [pageEditSuccess, setPageEditSuccess] = useState<string | null>(null)

  useEffect(() => {
    onSaving(savingOrder || creatingPage || savingPage || deletingPage)
  }, [savingOrder, creatingPage, savingPage, deletingPage, onSaving])
  useEffect(() => {
    setPages(initialPages)
  }, [initialPages])

  function handleMoveUp(index: number) {
    if (index <= 0) return
    const newPages = [...pages]
    const prevPage = newPages[index - 1]
    const currentPage = newPages[index]
    if (!prevPage || !currentPage) return
    newPages[index - 1] = currentPage
    newPages[index] = prevPage
    setPages(newPages)
    setOrderDirty(true)
    setPagesSuccess(null)
  }

  function handleMoveDown(index: number) {
    if (index >= pages.length - 1) return
    const newPages = [...pages]
    const nextPage = newPages[index + 1]
    const currentPage = newPages[index]
    if (!nextPage || !currentPage) return
    newPages[index + 1] = currentPage
    newPages[index] = nextPage
    setPages(newPages)
    setOrderDirty(true)
    setPagesSuccess(null)
  }

  async function handleSaveOrder() {
    setSavingOrder(true)
    setPagesError(null)
    setPagesSuccess(null)
    try {
      const orderPayload = pages.map((p) => ({ id: p.id, title: p.title, file: p.file }))
      const resp = await updateAdminPageOrder(orderPayload)
      setPages(resp.pages)
      onPagesChange(resp.pages)
      setOrderDirty(false)
      setPagesSuccess('Page order saved.')
      useSiteStore.getState().fetchConfig().catch((err: unknown) => { console.warn('Failed to refresh site config', err) })
    } catch (err) {
      if (err instanceof HTTPError && err.response.status === 401) {
        setPagesError('Session expired. Please log in again.')
      } else {
        setPagesError('Failed to save page order. Please try again.')
      }
    } finally {
      setSavingOrder(false)
    }
  }

  async function handleAddPage() {
    const trimmedId = newPageId.trim()
    const trimmedTitle = newPageTitle.trim()
    if (!trimmedId || !trimmedTitle) {
      setPagesError('Both ID and title are required.')
      return
    }
    setCreatingPage(true)
    setPagesError(null)
    setPagesSuccess(null)
    try {
      const page = await createAdminPage({ id: trimmedId, title: trimmedTitle })
      const nextPages = [...pages, page]
      setPages(nextPages)
      onPagesChange(nextPages)
      setNewPageId('')
      setNewPageTitle('')
      setShowAddForm(false)
      setPagesSuccess(`Page "${trimmedTitle}" created.`)
      useSiteStore.getState().fetchConfig().catch((err: unknown) => { console.warn('Failed to refresh site config', err) })
    } catch (err) {
      if (err instanceof HTTPError) {
        if (err.response.status === 409) {
          setPagesError(`A page with ID "${trimmedId}" already exists.`)
        } else if (err.response.status === 401) {
          setPagesError('Session expired. Please log in again.')
        } else {
          setPagesError('Failed to create page. Please try again.')
        }
      } else {
        setPagesError('Failed to create page. The server may be unavailable.')
      }
    } finally {
      setCreatingPage(false)
    }
  }

  function handleExpandPage(page: AdminPageConfig) {
    if (expandedPageId === page.id) {
      setExpandedPageId(null)
      setPageEditError(null)
      setPageEditSuccess(null)
      return
    }
    setExpandedPageId(page.id)
    setEditTitle(page.title)
    setEditContent(page.content ?? '')
    setPageEditError(null)
    setPageEditSuccess(null)
    setDeleteConfirmId(null)
  }

  async function handleSavePage() {
    if (expandedPageId === null) return
    const page = pages.find((p) => p.id === expandedPageId)
    if (!page) return
    if (!editTitle.trim()) {
      setPageEditError('Title is required.')
      return
    }
    setSavingPage(true)
    setPageEditError(null)
    setPageEditSuccess(null)
    try {
      const data: { title?: string; content?: string } = {}
      if (editTitle !== page.title) data.title = editTitle
      if (!BUILTIN_PAGE_IDS.has(page.id) && editContent !== (page.content ?? '')) {
        data.content = editContent
      }
      if (Object.keys(data).length > 0) {
        await updateAdminPage(page.id, data)
        const nextPages = pages.map((p) =>
          p.id === expandedPageId
            ? {
                ...p,
                title: editTitle,
                content: BUILTIN_PAGE_IDS.has(p.id) ? p.content : editContent,
              }
            : p,
        )
        setPages(nextPages)
        onPagesChange(nextPages)
        setPageEditSuccess('Page saved.')
        useSiteStore.getState().fetchConfig().catch((err: unknown) => { console.warn('Failed to refresh site config', err) })
      } else {
        setPageEditSuccess('No changes to save.')
      }
    } catch (err) {
      if (err instanceof HTTPError) {
        if (err.response.status === 401) {
          setPageEditError('Session expired. Please log in again.')
        } else if (err.response.status === 404) {
          setPageEditError('Page not found. It may have been deleted.')
        } else {
          setPageEditError('Failed to save page. Please try again.')
        }
      } else {
        setPageEditError('Failed to save page. The server may be unavailable.')
      }
    } finally {
      setSavingPage(false)
    }
  }

  async function handleDeletePage() {
    if (deleteConfirmId === null) return
    setDeletingPage(true)
    setPageEditError(null)
    setPageEditSuccess(null)
    try {
      await deleteAdminPage(deleteConfirmId)
      const nextPages = pages.filter((p) => p.id !== deleteConfirmId)
      setPages(nextPages)
      onPagesChange(nextPages)
      setExpandedPageId(null)
      setDeleteConfirmId(null)
      setPagesSuccess(`Page deleted.`)
      useSiteStore.getState().fetchConfig().catch((err: unknown) => { console.warn('Failed to refresh site config', err) })
    } catch (err) {
      if (err instanceof HTTPError) {
        if (err.response.status === 400) {
          setPageEditError('Cannot delete a built-in page.')
        } else if (err.response.status === 401) {
          setPageEditError('Session expired. Please log in again.')
        } else {
          setPageEditError('Failed to delete page. Please try again.')
        }
      } else {
        setPageEditError('Failed to delete page. The server may be unavailable.')
      }
    } finally {
      setDeletingPage(false)
    }
  }

  return (
    <section className="mb-8 p-5 bg-paper border border-border rounded-lg">
      <div className="flex items-center gap-2 mb-4">
        <FileText size={16} className="text-accent" />
        <h2 className="text-sm font-medium text-ink">Pages</h2>
      </div>

      {pagesError !== null && (
        <div className="mb-4 text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800/40 rounded-lg px-4 py-3">
          {pagesError}
        </div>
      )}
      {pagesSuccess !== null && (
        <div className="mb-4 text-sm text-green-700 dark:text-green-400 bg-green-50 dark:bg-green-950/30 border border-green-200 dark:border-green-800/40 rounded-lg px-4 py-3">
          {pagesSuccess}
        </div>
      )}

      {/* Page list */}
      <div className="space-y-2 mb-4">
        {pages.map((page, index) => (
          <div key={page.id} className="border border-border rounded-lg">
            {/* Page row */}
            <div className="flex items-center gap-3 px-4 py-3">
              <div className="flex items-center gap-1">
                <button
                  onClick={() => handleMoveUp(index)}
                  disabled={busy || index === 0}
                  className="p-1 text-muted hover:text-ink disabled:opacity-30 transition-colors"
                  aria-label={`Move ${page.title} up`}
                >
                  <ArrowUp size={14} />
                </button>
                <button
                  onClick={() => handleMoveDown(index)}
                  disabled={busy || index === pages.length - 1}
                  className="p-1 text-muted hover:text-ink disabled:opacity-30 transition-colors"
                  aria-label={`Move ${page.title} down`}
                >
                  <ArrowDown size={14} />
                </button>
              </div>

              <button
                onClick={() => handleExpandPage(page)}
                disabled={busy}
                className="flex items-center gap-2 flex-1 text-left disabled:opacity-50"
              >
                {expandedPageId === page.id ? (
                  <ChevronDown size={14} className="text-muted" />
                ) : (
                  <ChevronRight size={14} className="text-muted" />
                )}
                <span className="text-sm font-medium text-ink">{page.title}</span>
                <span className="text-xs text-muted">({page.id})</span>
              </button>

              {BUILTIN_PAGE_IDS.has(page.id) && (
                <span className="text-xs px-2 py-0.5 bg-accent/10 text-accent rounded-full">
                  built-in
                </span>
              )}
            </div>

            {/* Expanded edit section */}
            {expandedPageId === page.id && (
              <div className="border-t border-border px-4 py-4 space-y-4">
                {pageEditError !== null && (
                  <div className="text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800/40 rounded-lg px-4 py-3">
                    {pageEditError}
                  </div>
                )}
                {pageEditSuccess !== null && (
                  <div className="text-sm text-green-700 dark:text-green-400 bg-green-50 dark:bg-green-950/30 border border-green-200 dark:border-green-800/40 rounded-lg px-4 py-3">
                    {pageEditSuccess}
                  </div>
                )}

                <div>
                  <label
                    htmlFor={`page-title-${page.id}`}
                    className="block text-xs font-medium text-muted mb-1"
                  >
                    Title
                  </label>
                  <input
                    id={`page-title-${page.id}`}
                    type="text"
                    value={editTitle}
                    onChange={(e) => {
                      setEditTitle(e.target.value)
                      setPageEditSuccess(null)
                    }}
                    disabled={busy}
                    className="w-full px-3 py-2 bg-paper-warm border border-border rounded-lg
                             text-ink text-sm
                             focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/20
                             disabled:opacity-50"
                  />
                </div>

                {/* Content editor for non-builtin pages with files */}
                {!BUILTIN_PAGE_IDS.has(page.id) && page.file !== null && (
                  <div>
                    <label className="block text-xs font-medium text-muted mb-1">Content</label>
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                      <textarea
                        value={editContent}
                        onChange={(e) => {
                          setEditContent(e.target.value)
                          setPageEditSuccess(null)
                        }}
                        disabled={busy}
                        className="w-full min-h-[300px] p-4 bg-paper-warm border border-border rounded-lg
                                 font-mono text-sm leading-relaxed text-ink resize-y
                                 focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/20
                                 disabled:opacity-50"
                        spellCheck={false}
                      />
                      <div className="p-4 bg-paper border border-border rounded-lg overflow-y-auto min-h-[300px]">
                        <PagePreview markdown={editContent} />
                      </div>
                    </div>
                  </div>
                )}

                <div className="flex items-center gap-3">
                  <button
                    onClick={() => void handleSavePage()}
                    disabled={busy}
                    className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium bg-accent text-white rounded-lg
                             hover:bg-accent-light disabled:opacity-50 transition-colors"
                  >
                    <Save size={14} />
                    {savingPage ? 'Saving...' : 'Save Page'}
                  </button>
                </div>

                {/* Delete section for non-builtin pages */}
                {!BUILTIN_PAGE_IDS.has(page.id) && (
                  <div className="pt-4 border-t border-red-200 dark:border-red-800/40">
                    <h3 className="text-sm font-medium text-red-700 dark:text-red-400 mb-2">Danger Zone</h3>
                    <p className="text-sm text-muted mb-3">
                      Deleting this page will remove it from the site navigation and delete its
                      file. This action cannot be undone.
                    </p>
                    {deleteConfirmId === page.id ? (
                      <div className="flex items-center gap-3">
                        <button
                          onClick={() => void handleDeletePage()}
                          disabled={busy}
                          className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium
                                   bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50
                                   transition-colors"
                        >
                          <Trash2 size={14} />
                          {deletingPage ? 'Deleting...' : 'Confirm Delete'}
                        </button>
                        <button
                          onClick={() => setDeleteConfirmId(null)}
                          disabled={busy}
                          className="px-4 py-2 text-sm font-medium border border-border rounded-lg
                                   hover:bg-paper-warm disabled:opacity-50 transition-colors"
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setDeleteConfirmId(page.id)}
                        disabled={busy}
                        className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium
                                 text-red-600 dark:text-red-400 border border-red-300 dark:border-red-700 rounded-lg hover:bg-red-50 dark:hover:bg-red-950/30
                                 disabled:opacity-50 transition-colors"
                      >
                        <Trash2 size={14} />
                        Delete Page
                      </button>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Save order + Add page buttons */}
      <div className="flex items-center gap-3">
        {orderDirty && (
          <button
            onClick={() => void handleSaveOrder()}
            disabled={busy}
            className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium bg-accent text-white rounded-lg
                     hover:bg-accent-light disabled:opacity-50 transition-colors"
          >
            <Save size={14} />
            {savingOrder ? 'Saving...' : 'Save Order'}
          </button>
        )}
        <button
          onClick={() => {
            setShowAddForm(!showAddForm)
            setPagesError(null)
          }}
          disabled={busy}
          className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium
                   border border-border rounded-lg hover:bg-paper-warm
                   disabled:opacity-50 transition-colors"
        >
          <Plus size={14} />
          Add Page
        </button>
      </div>

      {/* Add page inline form */}
      {showAddForm && (
        <div className="mt-4 p-4 bg-paper-warm border border-border rounded-lg space-y-3">
          <div>
            <label htmlFor="new-page-id" className="block text-xs font-medium text-muted mb-1">
              Page ID *
            </label>
            <input
              id="new-page-id"
              type="text"
              value={newPageId}
              onChange={(e) => setNewPageId(e.target.value)}
              disabled={busy}
              placeholder="e.g. about"
              className="w-full px-3 py-2 bg-paper border border-border rounded-lg
                       text-ink text-sm font-mono
                       focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/20
                       disabled:opacity-50"
            />
            <p className="text-xs text-muted mt-1">
              Lowercase alphanumeric characters, hyphens, and underscores only.
            </p>
          </div>
          <div>
            <label
              htmlFor="new-page-title"
              className="block text-xs font-medium text-muted mb-1"
            >
              Title *
            </label>
            <input
              id="new-page-title"
              type="text"
              value={newPageTitle}
              onChange={(e) => setNewPageTitle(e.target.value)}
              disabled={busy}
              placeholder="e.g. About"
              className="w-full px-3 py-2 bg-paper border border-border rounded-lg
                       text-ink text-sm
                       focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/20
                       disabled:opacity-50"
            />
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={() => void handleAddPage()}
              disabled={busy || newPageId.trim().length === 0 || newPageTitle.trim().length === 0}
              className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium bg-accent text-white rounded-lg
                       hover:bg-accent-light disabled:opacity-50 transition-colors"
            >
              <Plus size={14} />
              {creatingPage ? 'Creating...' : 'Create Page'}
            </button>
            <button
              onClick={() => {
                setShowAddForm(false)
                setNewPageId('')
                setNewPageTitle('')
              }}
              disabled={busy}
              className="px-4 py-2 text-sm font-medium border border-border rounded-lg
                       hover:bg-paper-warm disabled:opacity-50 transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </section>
  )
}
