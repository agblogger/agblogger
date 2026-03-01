import { useEffect, useRef, useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import {
  Settings,
  FileText,
  Lock,
  ArrowUp,
  ArrowDown,
  Plus,
  Trash2,
  ChevronDown,
  ChevronRight,
  ArrowLeft,
  Save,
} from 'lucide-react'

import { useAuthStore } from '@/stores/authStore'
import { useSiteStore } from '@/stores/siteStore'
import { HTTPError } from '@/api/client'
import api from '@/api/client'
import { parseErrorDetail } from '@/api/parseError'
import type { AdminSiteSettings, AdminPageConfig } from '@/api/client'
import {
  fetchAdminSiteSettings,
  updateAdminSiteSettings,
  fetchAdminPages,
  createAdminPage,
  updateAdminPage,
  updateAdminPageOrder,
  deleteAdminPage,
  changeAdminPassword,
} from '@/api/admin'
import { useRenderedHtml } from '@/hooks/useKatex'
import SocialAccountsPanel from '@/components/crosspost/SocialAccountsPanel'

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
      } catch {
        if (requestRef.current === requestId) {
          setPreviewError(true)
        }
      }
    }, 500)
    return () => clearTimeout(timer)
  }, [markdown, hasContent])

  const rendered = useRenderedHtml(hasContent ? html : null)

  if (previewError) {
    return <p className="text-sm text-red-600 italic">Preview unavailable</p>
  }

  if (!rendered) {
    return <p className="text-sm text-muted italic">Preview will appear here...</p>
  }

  return <div className="prose max-w-none" dangerouslySetInnerHTML={{ __html: rendered }} />
}

export default function AdminPage() {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const isInitialized = useAuthStore((s) => s.isInitialized)

  // === Loading state ===
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  // === Site settings state ===
  const [siteSettings, setSiteSettings] = useState<AdminSiteSettings>({
    title: '',
    description: '',
    default_author: '',
    timezone: '',
  })
  const [siteError, setSiteError] = useState<string | null>(null)
  const [siteSuccess, setSiteSuccess] = useState<string | null>(null)
  const [savingSite, setSavingSite] = useState(false)

  // === Pages state ===
  const [pages, setPages] = useState<AdminPageConfig[]>([])
  const [pagesError, setPagesError] = useState<string | null>(null)
  const [pagesSuccess, setPagesSuccess] = useState<string | null>(null)
  const [savingOrder, setSavingOrder] = useState(false)
  const [orderDirty, setOrderDirty] = useState(false)

  // Add page form
  const [showAddForm, setShowAddForm] = useState(false)
  const [newPageId, setNewPageId] = useState('')
  const [newPageTitle, setNewPageTitle] = useState('')
  const [creatingPage, setCreatingPage] = useState(false)

  // Expanded page editing
  const [expandedPageId, setExpandedPageId] = useState<string | null>(null)
  const [editTitle, setEditTitle] = useState('')
  const [editContent, setEditContent] = useState('')
  const [savingPage, setSavingPage] = useState(false)
  const [deletingPage, setDeletingPage] = useState(false)
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null)
  const [pageEditError, setPageEditError] = useState<string | null>(null)
  const [pageEditSuccess, setPageEditSuccess] = useState<string | null>(null)

  // === Password state ===
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [passwordError, setPasswordError] = useState<string | null>(null)
  const [passwordSuccess, setPasswordSuccess] = useState<string | null>(null)
  const [savingPassword, setSavingPassword] = useState(false)

  // === Social accounts state ===
  const [socialBusy, setSocialBusy] = useState(false)

  const busy =
    savingSite ||
    savingOrder ||
    creatingPage ||
    savingPage ||
    deletingPage ||
    savingPassword ||
    socialBusy

  // === Auth redirect ===
  useEffect(() => {
    if (isInitialized && !user) {
      void navigate('/login', { replace: true })
    } else if (isInitialized && user && !user.is_admin) {
      void navigate('/', { replace: true })
    }
  }, [user, isInitialized, navigate])

  // === Load data ===
  useEffect(() => {
    if (!isInitialized || user?.is_admin !== true) return
    setLoading(true)
    setLoadError(null)
    void Promise.all([fetchAdminSiteSettings(), fetchAdminPages()])
      .then(([settings, pagesResp]) => {
        setSiteSettings(settings)
        setPages(pagesResp.pages)
      })
      .catch((err: unknown) => {
        if (err instanceof HTTPError && err.response.status === 401) {
          setLoadError('Session expired. Please log in again.')
        } else {
          setLoadError('Failed to load admin data. Please try again later.')
        }
      })
      .finally(() => {
        setLoading(false)
      })
  }, [isInitialized, user?.is_admin])

  // === Site settings handlers ===
  async function handleSaveSiteSettings() {
    if (!siteSettings.title.trim()) {
      setSiteError('Title is required.')
      return
    }
    setSavingSite(true)
    setSiteError(null)
    setSiteSuccess(null)
    try {
      const updated = await updateAdminSiteSettings(siteSettings)
      setSiteSettings(updated)
      setSiteSuccess('Site settings saved.')
      useSiteStore.getState().fetchConfig().catch(() => {})
    } catch (err) {
      if (err instanceof HTTPError) {
        if (err.response.status === 401) {
          setSiteError('Session expired. Please log in again.')
        } else {
          setSiteError('Failed to save settings. Please try again.')
        }
      } else {
        setSiteError('Failed to save settings. The server may be unavailable.')
      }
    } finally {
      setSavingSite(false)
    }
  }

  // === Page order handlers ===
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
      setOrderDirty(false)
      setPagesSuccess('Page order saved.')
      useSiteStore.getState().fetchConfig().catch(() => {})
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

  // === Add page handler ===
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
      setPages((prev) => [...prev, page])
      setNewPageId('')
      setNewPageTitle('')
      setShowAddForm(false)
      setPagesSuccess(`Page "${trimmedTitle}" created.`)
      useSiteStore.getState().fetchConfig().catch(() => {})
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

  // === Page edit handlers ===
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
        setPages((prev) =>
          prev.map((p) =>
            p.id === expandedPageId
              ? {
                  ...p,
                  title: editTitle,
                  content: BUILTIN_PAGE_IDS.has(p.id) ? p.content : editContent,
                }
              : p,
          ),
        )
        setPageEditSuccess('Page saved.')
        useSiteStore.getState().fetchConfig().catch(() => {})
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
      setPages((prev) => prev.filter((p) => p.id !== deleteConfirmId))
      setExpandedPageId(null)
      setDeleteConfirmId(null)
      setPagesSuccess(`Page deleted.`)
      useSiteStore.getState().fetchConfig().catch(() => {})
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

  // === Password handlers ===
  async function handleChangePassword() {
    setPasswordError(null)
    setPasswordSuccess(null)
    if (
      currentPassword.length === 0 ||
      newPassword.length === 0 ||
      confirmPassword.length === 0
    ) {
      setPasswordError('All fields are required.')
      return
    }
    if (newPassword !== confirmPassword) {
      setPasswordError('New passwords do not match.')
      return
    }
    if (newPassword.length < 8) {
      setPasswordError('New password must be at least 8 characters.')
      return
    }
    setSavingPassword(true)
    try {
      await changeAdminPassword({
        current_password: currentPassword,
        new_password: newPassword,
        confirm_password: confirmPassword,
      })
      setPasswordSuccess('Password changed successfully.')
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
    } catch (err) {
      if (err instanceof HTTPError) {
        if (err.response.status === 400) {
          const detail = await parseErrorDetail(err.response, 'Invalid request.')
          setPasswordError(detail)
        } else if (err.response.status === 401) {
          setPasswordError('Session expired. Please log in again.')
        } else {
          setPasswordError('Failed to change password. Please try again.')
        }
      } else {
        setPasswordError('Failed to change password. The server may be unavailable.')
      }
    } finally {
      setSavingPassword(false)
    }
  }

  // === Render guards ===
  if (!isInitialized || !user) {
    return null
  }

  if (!user.is_admin) {
    return null
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24" role="status" aria-label="Loading">
        <div className="w-6 h-6 border-2 border-accent/30 border-t-accent rounded-full animate-spin" />
      </div>
    )
  }

  if (loadError !== null) {
    return (
      <div className="text-center py-24">
        <p className="text-red-600">{loadError}</p>
        <Link to="/" className="text-accent text-sm hover:underline mt-4 inline-block">
          Back to home
        </Link>
      </div>
    )
  }

  return (
    <div className="animate-fade-in">
      <Link
        to="/"
        className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink transition-colors mb-6"
      >
        <ArrowLeft size={14} />
        Back
      </Link>

      <div className="flex items-center gap-3 mb-8">
        <Settings size={20} className="text-accent" />
        <h1 className="font-display text-3xl text-ink">Admin Panel</h1>
      </div>

      {/* === Section 1: Site Settings === */}
      <section className="mb-8 p-5 bg-paper border border-border rounded-lg">
        <div className="flex items-center gap-2 mb-4">
          <Settings size={16} className="text-accent" />
          <h2 className="text-sm font-medium text-ink">Site Settings</h2>
        </div>

        {siteError !== null && (
          <div className="mb-4 text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
            {siteError}
          </div>
        )}
        {siteSuccess !== null && (
          <div className="mb-4 text-sm text-green-700 bg-green-50 border border-green-200 rounded-lg px-4 py-3">
            {siteSuccess}
          </div>
        )}

        <div className="space-y-4">
          <div>
            <label htmlFor="site-title" className="block text-xs font-medium text-muted mb-1">
              Title *
            </label>
            <input
              id="site-title"
              type="text"
              value={siteSettings.title}
              onChange={(e) => {
                setSiteSettings({ ...siteSettings, title: e.target.value })
                setSiteSuccess(null)
              }}
              disabled={busy}
              className="w-full px-3 py-2 bg-paper-warm border border-border rounded-lg
                       text-ink text-sm
                       focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/20
                       disabled:opacity-50"
            />
          </div>

          <div>
            <label
              htmlFor="site-description"
              className="block text-xs font-medium text-muted mb-1"
            >
              Description
            </label>
            <input
              id="site-description"
              type="text"
              value={siteSettings.description}
              onChange={(e) => {
                setSiteSettings({ ...siteSettings, description: e.target.value })
                setSiteSuccess(null)
              }}
              disabled={busy}
              className="w-full px-3 py-2 bg-paper-warm border border-border rounded-lg
                       text-ink text-sm
                       focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/20
                       disabled:opacity-50"
            />
          </div>

          <div>
            <label
              htmlFor="site-default-author"
              className="block text-xs font-medium text-muted mb-1"
            >
              Default Author
            </label>
            <input
              id="site-default-author"
              type="text"
              value={siteSettings.default_author}
              onChange={(e) => {
                setSiteSettings({ ...siteSettings, default_author: e.target.value })
                setSiteSuccess(null)
              }}
              disabled={busy}
              className="w-full px-3 py-2 bg-paper-warm border border-border rounded-lg
                       text-ink text-sm
                       focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/20
                       disabled:opacity-50"
            />
          </div>

          <div>
            <label htmlFor="site-timezone" className="block text-xs font-medium text-muted mb-1">
              Timezone
            </label>
            <input
              id="site-timezone"
              type="text"
              value={siteSettings.timezone}
              onChange={(e) => {
                setSiteSettings({ ...siteSettings, timezone: e.target.value })
                setSiteSuccess(null)
              }}
              disabled={busy}
              placeholder="e.g. America/New_York"
              className="w-full px-3 py-2 bg-paper-warm border border-border rounded-lg
                       text-ink text-sm
                       focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/20
                       disabled:opacity-50"
            />
          </div>
        </div>

        <div className="mt-4">
          <button
            onClick={() => void handleSaveSiteSettings()}
            disabled={busy}
            className="flex items-center gap-1.5 px-5 py-2 text-sm font-medium bg-accent text-white rounded-lg
                     hover:bg-accent-light disabled:opacity-50 transition-colors"
          >
            <Save size={14} />
            {savingSite ? 'Saving...' : 'Save Settings'}
          </button>
        </div>
      </section>

      {/* === Section 2: Pages Management === */}
      <section className="mb-8 p-5 bg-paper border border-border rounded-lg">
        <div className="flex items-center gap-2 mb-4">
          <FileText size={16} className="text-accent" />
          <h2 className="text-sm font-medium text-ink">Pages</h2>
        </div>

        {pagesError !== null && (
          <div className="mb-4 text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
            {pagesError}
          </div>
        )}
        {pagesSuccess !== null && (
          <div className="mb-4 text-sm text-green-700 bg-green-50 border border-green-200 rounded-lg px-4 py-3">
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
                    <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
                      {pageEditError}
                    </div>
                  )}
                  {pageEditSuccess !== null && (
                    <div className="text-sm text-green-700 bg-green-50 border border-green-200 rounded-lg px-4 py-3">
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
                    <div className="pt-4 border-t border-red-200">
                      <h3 className="text-sm font-medium text-red-700 mb-2">Danger Zone</h3>
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
                                   text-red-600 border border-red-300 rounded-lg hover:bg-red-50
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

      {/* === Section 3: Change Password === */}
      <section className="mb-8 p-5 bg-paper border border-border rounded-lg">
        <div className="flex items-center gap-2 mb-4">
          <Lock size={16} className="text-accent" />
          <h2 className="text-sm font-medium text-ink">Change Password</h2>
        </div>

        {passwordError !== null && (
          <div className="mb-4 text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
            {passwordError}
          </div>
        )}
        {passwordSuccess !== null && (
          <div className="mb-4 text-sm text-green-700 bg-green-50 border border-green-200 rounded-lg px-4 py-3">
            {passwordSuccess}
          </div>
        )}

        <form
          onSubmit={(e) => {
            e.preventDefault()
            void handleChangePassword()
          }}
          className="space-y-4 max-w-md"
        >
          <div>
            <label
              htmlFor="current-password"
              className="block text-xs font-medium text-muted mb-1"
            >
              Current Password *
            </label>
            <input
              id="current-password"
              name="current-password"
              type="password"
              autoComplete="current-password"
              value={currentPassword}
              onChange={(e) => {
                setCurrentPassword(e.target.value)
                setPasswordError(null)
                setPasswordSuccess(null)
              }}
              disabled={busy}
              className="w-full px-3 py-2 bg-paper-warm border border-border rounded-lg
                       text-ink text-sm
                       focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/20
                       disabled:opacity-50"
            />
          </div>

          <div>
            <label htmlFor="new-password" className="block text-xs font-medium text-muted mb-1">
              New Password *
            </label>
            <input
              id="new-password"
              name="new-password"
              type="password"
              autoComplete="new-password"
              value={newPassword}
              onChange={(e) => {
                setNewPassword(e.target.value)
                setPasswordError(null)
                setPasswordSuccess(null)
              }}
              disabled={busy}
              className="w-full px-3 py-2 bg-paper-warm border border-border rounded-lg
                       text-ink text-sm
                       focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/20
                       disabled:opacity-50"
            />
            <p className="text-xs text-muted mt-1">At least 8 characters.</p>
          </div>

          <div>
            <label
              htmlFor="confirm-password"
              className="block text-xs font-medium text-muted mb-1"
            >
              Confirm New Password *
            </label>
            <input
              id="confirm-password"
              name="confirm-password"
              type="password"
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(e) => {
                setConfirmPassword(e.target.value)
                setPasswordError(null)
                setPasswordSuccess(null)
              }}
              disabled={busy}
              className="w-full px-3 py-2 bg-paper-warm border border-border rounded-lg
                       text-ink text-sm
                       focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/20
                       disabled:opacity-50"
            />
          </div>

          <div className="mt-4">
            <button
              type="submit"
              disabled={busy}
              className="flex items-center gap-1.5 px-5 py-2 text-sm font-medium bg-accent text-white rounded-lg
                       hover:bg-accent-light disabled:opacity-50 transition-colors"
            >
              <Lock size={14} />
              {savingPassword ? 'Changing...' : 'Change Password'}
            </button>
          </div>
        </form>
      </section>

      {/* === Section 4: Social Accounts === */}
      <SocialAccountsPanel busy={busy} onBusyChange={setSocialBusy} />
    </div>
  )
}
