import { useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'

import {
  fetchSubscriptionSettings,
  updateSubscriptionSettings,
  fetchBroadcasts,
  sendTestEmail,
  triggerBroadcast,
  type SubscriptionSettings,
  type BroadcastSummary,
} from '@/api/subscriptions'
import { fetchPosts } from '@/api/posts'
import type { PostSummary } from '@/api/client'
import { extractErrorDetail } from '@/api/parseError'
import { refreshSiteConfig } from '@/stores/siteStore'
import AlertBanner from '@/components/AlertBanner'
import ToggleSwitch from './ToggleSwitch'

interface Props {
  busy: boolean
  onBusyChange: (b: boolean) => void
}

const INPUT_CLASS =
  'w-full rounded-lg border border-border bg-paper px-3 py-2 text-sm text-ink placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-accent/40 disabled:opacity-50 disabled:cursor-not-allowed'

function isEnableAllowed(s: SubscriptionSettings): boolean {
  return (
    s.key_configured &&
    Boolean(s.from_email) &&
    Boolean(s.controller_name) &&
    Boolean(s.controller_contact) &&
    Boolean(s.privacy_policy_url) &&
    Boolean(s.postal_address)
  )
}

async function fetchAllPublishedPosts(): Promise<PostSummary[]> {
  const params = { per_page: 100, sort: 'created_at' as const, order: 'desc' as const }
  const firstPage = await fetchPosts({ ...params, page: 1 })
  const remainingPages = await Promise.all(
    Array.from(
      { length: Math.max(firstPage.total_pages - 1, 0) },
      (_, index) => fetchPosts({ ...params, page: index + 2 }),
    ),
  )
  const pages = [firstPage, ...remainingPages]
  return pages.flatMap((response) => response.posts).filter((post) => !post.is_draft)
}

export default function SubscriptionsPanel({ busy, onBusyChange }: Props) {
  const [settings, setSettings] = useState<SubscriptionSettings | null>(null)
  const [broadcasts, setBroadcasts] = useState<BroadcastSummary[]>([])
  const [publishedPosts, setPublishedPosts] = useState<PostSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [initError, setInitError] = useState<string | null>(null)

  // Settings form state
  const [apiKey, setApiKey] = useState('')
  const [fromEmail, setFromEmail] = useState('')
  const [fromName, setFromName] = useState('')
  const [controllerName, setControllerName] = useState('')
  const [controllerContact, setControllerContact] = useState('')
  const [privacyPolicyUrl, setPrivacyPolicyUrl] = useState('')
  const [postalAddress, setPostalAddress] = useState('')

  // UI feedback
  const [settingsError, setSettingsError] = useState<string | null>(null)
  const [settingsSuccess, setSettingsSuccess] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  // Broadcast section
  const [selectedPostPath, setSelectedPostPath] = useState('')
  const [broadcastError, setBroadcastError] = useState<string | null>(null)
  const [broadcastSuccess, setBroadcastSuccess] = useState<string | null>(null)
  const [broadcastBusy, setBroadcastBusy] = useState(false)

  // Test email section
  const [testEmail, setTestEmail] = useState('')
  const [testEmailError, setTestEmailError] = useState<string | null>(null)
  const [testEmailSuccess, setTestEmailSuccess] = useState<string | null>(null)
  const [testEmailBusy, setTestEmailBusy] = useState(false)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setInitError(null)
      try {
        const [s, b, posts] = await Promise.all([
          fetchSubscriptionSettings(),
          fetchBroadcasts(),
          fetchAllPublishedPosts(),
        ])
        if (cancelled) return
        setSettings(s)
        setFromEmail(s.from_email ?? '')
        setFromName(s.from_name ?? '')
        setControllerName(s.controller_name ?? '')
        setControllerContact(s.controller_contact ?? '')
        setPrivacyPolicyUrl(s.privacy_policy_url ?? '')
        setPostalAddress(s.postal_address ?? '')
        setBroadcasts(b.broadcasts)
        setPublishedPosts(posts)
      } catch (err) {
        if (cancelled) return
        setInitError(await extractErrorDetail(err, 'Failed to load subscription settings.'))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => { cancelled = true }
  }, [])

  async function handleToggleEnabled(value: boolean) {
    if (settings === null) return
    setSaving(true)
    onBusyChange(true)
    setSettingsError(null)
    setSettingsSuccess(null)
    try {
      const updated = await updateSubscriptionSettings({ enabled: value })
      setSettings(updated)
      refreshSiteConfig()
    } catch (err) {
      setSettingsError(await extractErrorDetail(err, 'Failed to update setting. Please try again.'))
    } finally {
      setSaving(false)
      onBusyChange(false)
    }
  }

  async function handleSaveSettings() {
    setSaving(true)
    onBusyChange(true)
    setSettingsError(null)
    setSettingsSuccess(null)
    try {
      const patch: Parameters<typeof updateSubscriptionSettings>[0] = {
        from_email: fromEmail || null,
        from_name: fromName || null,
        controller_name: controllerName || null,
        controller_contact: controllerContact || null,
        privacy_policy_url: privacyPolicyUrl || null,
        postal_address: postalAddress || null,
      }
      if (apiKey.length > 0) {
        patch.api_key = apiKey
      }
      const updated = await updateSubscriptionSettings(patch)
      setSettings(updated)
      setApiKey('')
      setSettingsSuccess('Settings saved.')
    } catch (err) {
      setSettingsError(await extractErrorDetail(err, 'Failed to save settings. Please try again.'))
    } finally {
      setSaving(false)
      onBusyChange(false)
    }
  }

  async function handleSendBroadcast() {
    const post = publishedPosts.find((p) => p.file_path === selectedPostPath)
    if (post === undefined) return
    const confirmed = window.confirm(`Email subscribers about '${post.title}'?`)
    if (!confirmed) return
    setBroadcastBusy(true)
    onBusyChange(true)
    setBroadcastError(null)
    setBroadcastSuccess(null)
    try {
      const result = await triggerBroadcast(selectedPostPath)
      setBroadcastSuccess(result.message)
      const b = await fetchBroadcasts()
      setBroadcasts(b.broadcasts)
    } catch (err) {
      setBroadcastError(await extractErrorDetail(err, 'Failed to send broadcast. Please try again.'))
    } finally {
      setBroadcastBusy(false)
      onBusyChange(false)
    }
  }

  async function handleSendTestEmail() {
    setTestEmailBusy(true)
    onBusyChange(true)
    setTestEmailError(null)
    setTestEmailSuccess(null)
    try {
      const result = await sendTestEmail(testEmail)
      setTestEmailSuccess(result.message)
    } catch (err) {
      setTestEmailError(await extractErrorDetail(err, 'Failed to send test email. Please try again.'))
    } finally {
      setTestEmailBusy(false)
      onBusyChange(false)
    }
  }

  const allBusy = busy || saving || broadcastBusy || testEmailBusy

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16" aria-label="Loading" role="status">
        <Loader2 size={24} className="text-accent animate-spin" aria-hidden="true" />
      </div>
    )
  }

  if (initError !== null && settings === null) {
    return <AlertBanner variant="error">{initError}</AlertBanner>
  }

  const enableAllowed = settings !== null && isEnableAllowed(settings)

  return (
    <div className="space-y-8">

      {/* ── Settings section ── */}
      <section className="space-y-4">
        <h2 className="font-display text-xl text-ink">Email Settings</h2>

        {/* Enable toggle */}
        <div className="flex items-center gap-4">
          <ToggleSwitch
            id="subscriptions-enabled"
            label="Enable subscriptions"
            checked={settings?.enabled ?? false}
            disabled={allBusy || !enableAllowed}
            onChange={(value) => void handleToggleEnabled(value)}
          />
          {!enableAllowed && (
            <span className="text-xs text-muted">
              Requires API key + from email + all compliance fields.
            </span>
          )}
        </div>

        {/* Subscriber count */}
        <div className="bg-surface border border-border rounded-lg px-5 py-4 inline-block">
          <p className="text-xs text-muted uppercase tracking-wide mb-1">Subscribers</p>
          <p className="text-2xl font-semibold text-ink">
            {settings?.subscriber_count !== null && settings?.subscriber_count !== undefined
              ? settings.subscriber_count.toLocaleString()
              : 'unavailable'}
          </p>
        </div>

        {settingsError !== null && (
          <AlertBanner variant="error">{settingsError}</AlertBanner>
        )}
        {settingsSuccess !== null && (
          <AlertBanner variant="success">{settingsSuccess}</AlertBanner>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {/* API Key */}
          <div className="sm:col-span-2">
            <label className="block text-sm text-muted mb-1" htmlFor="api-key">
              Resend API key{' '}
              <span className={settings?.key_configured === true ? 'text-green-600 dark:text-green-400' : 'text-muted'}>
                {settings?.key_configured === true ? '(configured)' : '(not set)'}
              </span>
            </label>
            <input
              id="api-key"
              type="password"
              value={apiKey}
              disabled={allBusy}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={
                settings?.key_configured === true
                  ? 'configured — enter to replace'
                  : 'not set — paste API key here'
              }
              className={INPUT_CLASS}
            />
          </div>

          {/* From Email */}
          <div>
            <label className="block text-sm text-muted mb-1" htmlFor="from-email">
              From email
            </label>
            <input
              id="from-email"
              type="email"
              value={fromEmail}
              disabled={allBusy}
              onChange={(e) => setFromEmail(e.target.value)}
              placeholder="sender@example.com"
              className={INPUT_CLASS}
            />
          </div>

          {/* From Name */}
          <div>
            <label className="block text-sm text-muted mb-1" htmlFor="from-name">
              From name
            </label>
            <input
              id="from-name"
              type="text"
              value={fromName}
              disabled={allBusy}
              onChange={(e) => setFromName(e.target.value)}
              placeholder="Your Blog Name"
              className={INPUT_CLASS}
            />
          </div>

          {/* Controller Name */}
          <div>
            <label className="block text-sm text-muted mb-1" htmlFor="controller-name">
              Data controller name
            </label>
            <input
              id="controller-name"
              type="text"
              value={controllerName}
              disabled={allBusy}
              onChange={(e) => setControllerName(e.target.value)}
              placeholder="Your Name / Organisation"
              className={INPUT_CLASS}
            />
          </div>

          {/* Controller Contact */}
          <div>
            <label className="block text-sm text-muted mb-1" htmlFor="controller-contact">
              Controller contact
            </label>
            <input
              id="controller-contact"
              type="text"
              value={controllerContact}
              disabled={allBusy}
              onChange={(e) => setControllerContact(e.target.value)}
              placeholder="privacy@example.com"
              className={INPUT_CLASS}
            />
          </div>

          {/* Privacy Policy URL */}
          <div>
            <label className="block text-sm text-muted mb-1" htmlFor="privacy-policy-url">
              Privacy policy URL
            </label>
            <input
              id="privacy-policy-url"
              type="url"
              value={privacyPolicyUrl}
              disabled={allBusy}
              onChange={(e) => setPrivacyPolicyUrl(e.target.value)}
              placeholder="https://example.com/privacy"
              className={INPUT_CLASS}
            />
          </div>

          {/* Postal Address */}
          <div>
            <label className="block text-sm text-muted mb-1" htmlFor="postal-address">
              Postal address (email footer)
            </label>
            <input
              id="postal-address"
              type="text"
              value={postalAddress}
              disabled={allBusy}
              onChange={(e) => setPostalAddress(e.target.value)}
              placeholder="123 Main St, City, Country"
              className={INPUT_CLASS}
            />
          </div>
        </div>

        <button
          type="button"
          disabled={allBusy}
          onClick={() => void handleSaveSettings()}
          className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          Save settings
        </button>
      </section>

      {/* ── Send broadcast section ── */}
      <section className="space-y-4 border-t border-border pt-8">
        <h2 className="font-display text-xl text-ink">Send to Subscribers</h2>

        {broadcastError !== null && (
          <AlertBanner variant="error">{broadcastError}</AlertBanner>
        )}
        {broadcastSuccess !== null && (
          <AlertBanner variant="success">{broadcastSuccess}</AlertBanner>
        )}

        <div className="flex flex-wrap items-end gap-3">
          <div className="flex-1 min-w-48">
            <label className="block text-sm text-muted mb-1" htmlFor="post-select">
              Select post
            </label>
            <select
              id="post-select"
              value={selectedPostPath}
              disabled={allBusy || publishedPosts.length === 0}
              onChange={(e) => setSelectedPostPath(e.target.value)}
              aria-label="Select post"
              className={INPUT_CLASS}
            >
              <option value="">— choose a published post —</option>
              {publishedPosts.map((p) => (
                <option key={p.file_path} value={p.file_path}>
                  {p.title}
                </option>
              ))}
            </select>
          </div>
          <button
            type="button"
            disabled={allBusy || selectedPostPath === ''}
            onClick={() => void handleSendBroadcast()}
            className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            Send broadcast
          </button>
        </div>
      </section>

      {/* ── Send test email section ── */}
      <section className="space-y-4 border-t border-border pt-8">
        <h2 className="font-display text-xl text-ink">Send Test Email</h2>

        {testEmailError !== null && (
          <AlertBanner variant="error">{testEmailError}</AlertBanner>
        )}
        {testEmailSuccess !== null && (
          <AlertBanner variant="success">{testEmailSuccess}</AlertBanner>
        )}

        <div className="flex flex-wrap items-end gap-3">
          <div className="flex-1 min-w-48">
            <label className="block text-sm text-muted mb-1" htmlFor="test-email">
              Test email address
            </label>
            <input
              id="test-email"
              type="email"
              value={testEmail}
              disabled={allBusy}
              onChange={(e) => setTestEmail(e.target.value)}
              placeholder={settings?.from_email ?? 'you@example.com'}
              className={INPUT_CLASS}
            />
          </div>
          <button
            type="button"
            disabled={allBusy || testEmail === ''}
            onClick={() => void handleSendTestEmail()}
            className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            Send test email
          </button>
        </div>
      </section>

      {/* ── Broadcast history section ── */}
      <section className="space-y-4 border-t border-border pt-8">
        <h2 className="font-display text-xl text-ink">Broadcast History</h2>

        {broadcasts.length === 0 ? (
          <p className="text-sm text-muted">No broadcasts yet.</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-paper-warm">
                  <th className="px-4 py-3 text-left text-xs font-medium text-muted uppercase tracking-wide">
                    Post
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-muted uppercase tracking-wide">
                    Sent at
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-muted uppercase tracking-wide">
                    Status
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-muted uppercase tracking-wide">
                    Error
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {broadcasts.map((b) => (
                  <tr key={b.id} className="bg-paper hover:bg-paper-warm transition-colors">
                    <td className="px-4 py-3 text-ink">{b.post_title}</td>
                    <td className="px-4 py-3 text-muted">
                      {new Date(b.sent_at).toLocaleString()}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
                          b.status === 'sent'
                            ? 'bg-green-100 text-green-700 dark:bg-green-950/40 dark:text-green-400'
                            : b.status === 'failed'
                              ? 'bg-red-100 text-red-700 dark:bg-red-950/40 dark:text-red-400'
                              : 'bg-surface text-muted'
                        }`}
                      >
                        {b.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-muted text-xs">
                      {b.error ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
