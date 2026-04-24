import { useEffect, useRef, useState } from 'react'
import { Share2, Trash2, Plus, Loader2 } from 'lucide-react'

import {
  deleteSocialAccount,
  authorizeBluesky,
  authorizeMastodon,
  authorizeX,
  authorizeFacebook,
  fetchFacebookPages,
  selectFacebookPage,
} from '@/api/crosspost'
import type { SocialAccount, FacebookPage } from '@/api/crosspost'
import { extractErrorDetail } from '@/api/parseError'
import PlatformIcon from '@/components/crosspost/PlatformIcon'
import { formatLocalDate } from '@/utils/date'
import { useSocialAccounts } from '@/hooks/useSocialAccounts'

interface SocialAccountsPanelProps {
  busy: boolean
  onBusyChange: (busy: boolean) => void
}

type PlatformKey = 'bluesky' | 'facebook' | 'mastodon' | 'x'

const PLATFORM_DISPLAY_NAMES: Record<PlatformKey, string> = {
  bluesky: 'Bluesky',
  facebook: 'Facebook',
  mastodon: 'Mastodon',
  x: 'X',
}

function getPlatformDisplayName(platform: string): string {
  return (PLATFORM_DISPLAY_NAMES as Record<string, string>)[platform] ?? platform
}

function sortSocialAccounts(accts: SocialAccount[]): SocialAccount[] {
  return [...accts].sort((left, right) =>
    getPlatformDisplayName(left.platform).localeCompare(
      getPlatformDisplayName(right.platform),
      undefined,
      { sensitivity: 'base' },
    ),
  )
}

export default function SocialAccountsPanel({ busy, onBusyChange }: SocialAccountsPanelProps) {
  const { data: rawAccounts = [], error: loadErr, isLoading: loading, mutate: mutateAccounts } = useSocialAccounts()
  const accounts = sortSocialAccounts(rawAccounts)

  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  // Connect form state
  const [connectingPlatform, setConnectingPlatform] = useState<
    'bluesky' | 'mastodon' | 'x' | 'facebook' | null
  >(null)
  const [handle, setHandle] = useState('')
  const [instanceUrl, setInstanceUrl] = useState('')
  const [submitting, setSubmitting] = useState(false)

  // Facebook page selection state
  const [facebookPages, setFacebookPages] = useState<FacebookPage[]>([])
  const [facebookPageState, setFacebookPageState] = useState<string | null>(null)
  const [selectingPage, setSelectingPage] = useState(false)

  // Disconnect confirmation state
  const [deleteConfirmId, setDeleteConfirmId] = useState<number | null>(null)
  const [deleting, setDeleting] = useState(false)

  const localBusy = submitting || deleting || selectingPage
  const onBusyChangeRef = useRef(onBusyChange)
  onBusyChangeRef.current = onBusyChange

  useEffect(() => {
    onBusyChangeRef.current(localBusy)
  }, [localBusy])

  useEffect(() => {
    if (loadErr === undefined) {
      setError(null)
      return
    }
    void extractErrorDetail(loadErr, 'Failed to load social accounts.').then(setError)
  }, [loadErr])

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const fbPagesState = params.get('fb_pages')
    if (fbPagesState !== null) {
      setFacebookPageState(fbPagesState)
      const url = new URL(window.location.href)
      url.searchParams.delete('fb_pages')
      window.history.replaceState({}, '', url.toString())

      void (async () => {
        try {
          const pages = await fetchFacebookPages(fbPagesState)
          setFacebookPages(pages)
        } catch (err) {
          setError(await extractErrorDetail(err, 'Failed to load Facebook Pages. Please try again.'))
          setFacebookPageState(null)
        }
      })()
    }
  }, [])

  async function handleConnectBluesky() {
    const trimmed = handle.trim()
    if (!trimmed) return
    setSubmitting(true)
    setError(null)
    setSuccess(null)
    try {
      const { authorization_url } = await authorizeBluesky(trimmed)
      window.location.href = authorization_url
    } catch (err) {
      setError(
        await extractErrorDetail(err, 'Failed to start Bluesky authorization. Please try again.'),
      )
      setSubmitting(false)
    }
  }

  async function handleConnectMastodon() {
    const trimmed = instanceUrl.trim()
    if (!trimmed) return
    setSubmitting(true)
    setError(null)
    setSuccess(null)
    try {
      const { authorization_url } = await authorizeMastodon(trimmed)
      window.location.href = authorization_url
    } catch (err) {
      setError(
        await extractErrorDetail(err, 'Failed to start Mastodon authorization. Please try again.'),
      )
      setSubmitting(false)
    }
  }

  async function handleConnectX() {
    setSubmitting(true)
    setError(null)
    setSuccess(null)
    try {
      const { authorization_url } = await authorizeX()
      window.location.href = authorization_url
    } catch (err) {
      setError(await extractErrorDetail(err, 'Failed to start X authorization. Please try again.'))
      setSubmitting(false)
    }
  }

  async function handleConnectFacebook() {
    setSubmitting(true)
    setError(null)
    setSuccess(null)
    try {
      const { authorization_url } = await authorizeFacebook()
      window.location.href = authorization_url
    } catch (err) {
      setError(
        await extractErrorDetail(
          err,
          'Failed to start Facebook authorization. Please try again.',
        ),
      )
      setSubmitting(false)
    }
  }

  async function handleSelectFacebookPage(pageId: string) {
    if (facebookPageState === null) return
    setSelectingPage(true)
    setError(null)
    try {
      const result = await selectFacebookPage(facebookPageState, pageId)
      setFacebookPageState(null)
      setFacebookPages([])
      setSuccess(`Connected Facebook Page: ${result.account_name}`)
      await mutateAccounts()
    } catch (err) {
      setError(
        await extractErrorDetail(err, 'Failed to connect Facebook Page. Please try again.'),
      )
    } finally {
      setSelectingPage(false)
    }
  }

  async function handleDisconnect(accountId: number) {
    setDeleting(true)
    setError(null)
    setSuccess(null)
    try {
      await deleteSocialAccount(accountId)
      await mutateAccounts(
        (current) => (current ?? []).filter((a) => a.id !== accountId),
        { revalidate: true },
      )
      setDeleteConfirmId(null)
      setSuccess('Account disconnected.')
    } catch (err) {
      setError(await extractErrorDetail(err, 'Failed to disconnect account. Please try again.'))
    } finally {
      setDeleting(false)
    }
  }

  const allBusy = busy || localBusy

  return (
    <section className="mb-8 p-5 bg-paper border border-border rounded-lg">
      <div className="flex items-center gap-2 mb-4">
        <Share2 size={16} className="text-accent" />
        <h2 className="text-sm font-medium text-ink">Social Accounts</h2>
      </div>

      {error !== null && (
        <div className="mb-4 text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800/40 rounded-lg px-4 py-3">
          {error}
        </div>
      )}
      {success !== null && (
        <div className="mb-4 text-sm text-green-700 dark:text-green-400 bg-green-50 dark:bg-green-950/30 border border-green-200 dark:border-green-800/40 rounded-lg px-4 py-3">
          {success}
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-6">
          <Loader2 size={20} className="text-accent animate-spin" />
        </div>
      ) : (
        <>
          {/* Connected accounts list */}
          {accounts.length > 0 && (
            <div className="space-y-2 mb-4">
              {accounts.map((account) => (
                <div
                  key={account.id}
                  className="flex items-center gap-3 px-4 py-3 border border-border rounded-lg"
                >
                  <PlatformIcon platform={account.platform} size={20} className="text-muted" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-ink truncate">
                      {account.account_name ?? account.platform}
                    </p>
                    <p className="text-xs text-muted">
                      Connected {formatLocalDate(account.created_at)}
                    </p>
                  </div>
                  {deleteConfirmId === account.id ? (
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-red-600 dark:text-red-400">Confirm disconnect?</span>
                      <button
                        onClick={() => void handleDisconnect(account.id)}
                        disabled={allBusy}
                        className="px-3 py-1 text-xs font-medium bg-red-600 text-white rounded-lg
                                 hover:bg-red-700 disabled:opacity-50 transition-colors"
                      >
                        {deleting ? 'Removing...' : 'Confirm'}
                      </button>
                      <button
                        onClick={() => setDeleteConfirmId(null)}
                        disabled={allBusy}
                        className="px-3 py-1 text-xs font-medium border border-border rounded-lg
                                 hover:bg-paper-warm disabled:opacity-50 transition-colors"
                      >
                        Cancel
                      </button>
                    </div>
                  ) : (
                    <button
                      onClick={() => {
                        setDeleteConfirmId(account.id)
                        setSuccess(null)
                      }}
                      disabled={allBusy}
                      aria-label={`Disconnect ${account.account_name ?? account.platform}`}
                      className="p-1.5 text-muted hover:text-red-600 dark:hover:text-red-400 disabled:opacity-50 transition-colors"
                    >
                      <Trash2 size={14} />
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Connect buttons / inline forms */}
          <div className="space-y-3">
            {/* Bluesky connect */}
            {connectingPlatform === 'bluesky' ? (
              <div className="p-4 bg-paper-warm border border-border rounded-lg space-y-3">
                <label
                  htmlFor="bluesky-handle"
                  className="block text-xs font-medium text-muted mb-1"
                >
                  Bluesky Handle
                </label>
                <input
                  id="bluesky-handle"
                  type="text"
                  value={handle}
                  onChange={(e) => setHandle(e.target.value)}
                  disabled={allBusy}
                  placeholder="alice.bsky.social"
                  className="w-full px-3 py-2 bg-paper-warm border border-border rounded-lg
                           text-ink text-sm
                           focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/20
                           disabled:opacity-50"
                />
                <div className="flex items-center gap-3">
                  <button
                    onClick={() => void handleConnectBluesky()}
                    disabled={allBusy || handle.trim().length === 0}
                    className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium bg-accent text-white rounded-lg
                             hover:bg-accent-light disabled:opacity-50 transition-colors"
                  >
                    <Plus size={14} />
                    {submitting ? 'Connecting...' : 'Connect'}
                  </button>
                  <button
                    onClick={() => {
                      setConnectingPlatform(null)
                      setHandle('')
                    }}
                    disabled={allBusy}
                    className="px-4 py-2 text-sm font-medium border border-border rounded-lg
                             hover:bg-paper-warm disabled:opacity-50 transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <div className="flex items-center gap-3 px-4 py-3 border border-dashed border-border rounded-lg">
                <PlatformIcon platform="bluesky" size={20} className="text-muted" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-ink">Bluesky</p>
                  <p className="text-xs text-muted">Post to your Bluesky account</p>
                </div>
                <button
                  onClick={() => {
                    setConnectingPlatform('bluesky')
                    setInstanceUrl('')
                    setError(null)
                    setSuccess(null)
                  }}
                  disabled={allBusy}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium
                           border border-border rounded-lg hover:bg-paper-warm
                           disabled:opacity-50 transition-colors"
                >
                  <Plus size={12} />
                  Connect Bluesky
                </button>
              </div>
            )}

            {/* Facebook connect */}
            {connectingPlatform === 'facebook' ? (
              <div className="p-4 bg-paper-warm border border-border rounded-lg space-y-3">
                <p className="text-xs text-muted">
                  You will be redirected to Facebook to authorize AgBlogger and select a Page.
                </p>
                <div className="flex items-center gap-3">
                  <button
                    onClick={() => void handleConnectFacebook()}
                    disabled={allBusy}
                    className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium bg-accent text-white rounded-lg
                             hover:bg-accent-light disabled:opacity-50 transition-colors"
                  >
                    <Plus size={14} />
                    {submitting ? 'Connecting...' : 'Connect'}
                  </button>
                  <button
                    onClick={() => setConnectingPlatform(null)}
                    disabled={allBusy}
                    className="px-4 py-2 text-sm font-medium border border-border rounded-lg
                             hover:bg-paper-warm disabled:opacity-50 transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <div className="flex items-center gap-3 px-4 py-3 border border-dashed border-border rounded-lg">
                <PlatformIcon platform="facebook" size={20} className="text-muted" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-ink">Facebook</p>
                  <p className="text-xs text-muted">Post to your Facebook Page</p>
                </div>
                <button
                  onClick={() => {
                    setConnectingPlatform('facebook')
                    setError(null)
                    setSuccess(null)
                  }}
                  disabled={allBusy}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium
                           border border-border rounded-lg hover:bg-paper-warm
                           disabled:opacity-50 transition-colors"
                >
                  <Plus size={12} />
                  Connect Facebook
                </button>
              </div>
            )}

            {/* Mastodon connect */}
            {connectingPlatform === 'mastodon' ? (
              <div className="p-4 bg-paper-warm border border-border rounded-lg space-y-3">
                <label
                  htmlFor="mastodon-instance"
                  className="block text-xs font-medium text-muted mb-1"
                >
                  Mastodon Instance URL
                </label>
                <input
                  id="mastodon-instance"
                  type="text"
                  value={instanceUrl}
                  onChange={(e) => setInstanceUrl(e.target.value)}
                  disabled={allBusy}
                  placeholder="https://mastodon.social"
                  className="w-full px-3 py-2 bg-paper-warm border border-border rounded-lg
                           text-ink text-sm
                           focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/20
                           disabled:opacity-50"
                />
                <div className="flex items-center gap-3">
                  <button
                    onClick={() => void handleConnectMastodon()}
                    disabled={allBusy || instanceUrl.trim().length === 0}
                    className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium bg-accent text-white rounded-lg
                             hover:bg-accent-light disabled:opacity-50 transition-colors"
                  >
                    <Plus size={14} />
                    {submitting ? 'Connecting...' : 'Connect'}
                  </button>
                  <button
                    onClick={() => {
                      setConnectingPlatform(null)
                      setInstanceUrl('')
                    }}
                    disabled={allBusy}
                    className="px-4 py-2 text-sm font-medium border border-border rounded-lg
                             hover:bg-paper-warm disabled:opacity-50 transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <div className="flex items-center gap-3 px-4 py-3 border border-dashed border-border rounded-lg">
                <PlatformIcon platform="mastodon" size={20} className="text-muted" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-ink">Mastodon</p>
                  <p className="text-xs text-muted">Post to your Mastodon instance</p>
                </div>
                <button
                  onClick={() => {
                    setConnectingPlatform('mastodon')
                    setHandle('')
                    setError(null)
                    setSuccess(null)
                  }}
                  disabled={allBusy}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium
                           border border-border rounded-lg hover:bg-paper-warm
                           disabled:opacity-50 transition-colors"
                >
                  <Plus size={12} />
                  Connect Mastodon
                </button>
              </div>
            )}

            {/* X connect */}
            {connectingPlatform === 'x' ? (
              <div className="p-4 bg-paper-warm border border-border rounded-lg space-y-3">
                <p className="text-xs text-muted">
                  You will be redirected to X to authorize AgBlogger.
                </p>
                <div className="flex items-center gap-3">
                  <button
                    onClick={() => void handleConnectX()}
                    disabled={allBusy}
                    className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium bg-accent text-white rounded-lg
                             hover:bg-accent-light disabled:opacity-50 transition-colors"
                  >
                    <Plus size={14} />
                    {submitting ? 'Connecting...' : 'Connect'}
                  </button>
                  <button
                    onClick={() => setConnectingPlatform(null)}
                    disabled={allBusy}
                    className="px-4 py-2 text-sm font-medium border border-border rounded-lg
                             hover:bg-paper-warm disabled:opacity-50 transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <div className="flex items-center gap-3 px-4 py-3 border border-dashed border-border rounded-lg">
                <PlatformIcon platform="x" size={20} className="text-muted" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-ink">X</p>
                  <p className="text-xs text-muted">Post tweets to your X account</p>
                </div>
                <button
                  onClick={() => {
                    setConnectingPlatform('x')
                    setError(null)
                    setSuccess(null)
                  }}
                  disabled={allBusy}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium
                           border border-border rounded-lg hover:bg-paper-warm
                           disabled:opacity-50 transition-colors"
                >
                  <Plus size={12} />
                  Connect X
                </button>
              </div>
            )}
          </div>

          {/* Facebook page picker */}
          {facebookPageState !== null && (
            <div className="mt-4 p-4 bg-blue-50 border border-blue-200 rounded-lg space-y-3">
              <p className="text-sm font-medium text-ink">Select a Facebook Page</p>
              <p className="text-xs text-muted">
                Choose which Page AgBlogger should post to:
              </p>
              <div className="space-y-2">
                {facebookPages.map((page) => (
                  <button
                    key={page.id}
                    onClick={() => void handleSelectFacebookPage(page.id)}
                    disabled={selectingPage}
                    className="w-full text-left px-4 py-3 border border-border rounded-lg
                             hover:bg-paper-warm disabled:opacity-50 transition-colors"
                  >
                    <span className="text-sm font-medium text-ink">{page.name}</span>
                  </button>
                ))}
              </div>
              <button
                onClick={() => {
                  setFacebookPageState(null)
                  setFacebookPages([])
                }}
                disabled={selectingPage}
                className="px-4 py-2 text-sm font-medium border border-border rounded-lg
                         hover:bg-paper-warm disabled:opacity-50 transition-colors"
              >
                Cancel
              </button>
            </div>
          )}
        </>
      )}
    </section>
  )
}
