import { lazy, Suspense, useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { Settings } from 'lucide-react'

import { useRequireAdmin } from '@/hooks/useRequireAdmin'
import LoadingSpinner from '@/components/LoadingSpinner'
import BackLink from '@/components/BackLink'
import { HTTPError } from '@/api/client'
import type { AdminSiteSettings, AdminPageConfig } from '@/api/client'
import { useAdminSiteSettings, useAdminPages } from '@/hooks/useAdminData'
import SiteSettingsSection from '@/components/admin/SiteSettingsSection'
import PagesSection from '@/components/admin/PagesSection'
import AccountSection from '@/components/admin/AccountSection'
import SocialAccountsPanel from '@/components/crosspost/SocialAccountsPanel'
import { useUnsavedChanges } from '@/hooks/useUnsavedChanges'

const AnalyticsPanel = lazy(() => import('@/components/admin/AnalyticsPanel'))

const ADMIN_TABS = [
  { key: 'settings', label: 'Settings' },
  { key: 'pages', label: 'Pages' },
  { key: 'account', label: 'Account' },
  { key: 'social', label: 'Social' },
  { key: 'analytics', label: 'Analytics' },
] as const

type AdminTabKey = (typeof ADMIN_TABS)[number]['key']
const VALID_TAB_KEYS: Set<AdminTabKey> = new Set(ADMIN_TABS.map((t) => t.key))

const EMPTY_SITE_SETTINGS: AdminSiteSettings = { title: '', description: '', timezone: '', password_change_disabled: false, favicon: null }

export default function AdminPage() {
  const location = useLocation()
  const { isReady } = useRequireAdmin()
  const tabParam = new URLSearchParams(location.search).get('tab')
  const initialTab: AdminTabKey =
    tabParam !== null && VALID_TAB_KEYS.has(tabParam as AdminTabKey)
      ? (tabParam as AdminTabKey)
      : 'settings'

  // === SWR data (only fetch when auth is ready) ===
  const { data: siteSettingsData, error: siteError, isLoading: siteLoading } = useAdminSiteSettings(isReady)
  const { data: pagesData, error: pagesError, isLoading: pagesLoading } = useAdminPages(isReady)
  const loading = siteLoading || pagesLoading
  const firstError = siteError ?? pagesError
  const loadError = firstError !== undefined
    ? firstError instanceof HTTPError && firstError.response.status === 401
      ? 'Session expired. Please log in again.'
      : 'Failed to load admin data. Please try again later.'
    : null

  // === Tab navigation ===
  const [activeTab, setActiveTab] = useState<AdminTabKey>(initialTab)

  // === Mutable local overrides (null = use SWR data, non-null = user has made local changes) ===
  const [siteSettingsOverride, setSiteSettingsOverride] = useState<AdminSiteSettings | null>(null)
  const [pagesOverride, setPagesOverride] = useState<AdminPageConfig[] | null>(null)

  // Derive effective values: prefer local override, fall back to SWR data
  const siteSettings = siteSettingsOverride ?? siteSettingsData ?? EMPTY_SITE_SETTINGS
  const pages = pagesOverride ?? pagesData?.pages ?? []

  // === Busy tracking from sections ===
  const [siteSaving, setSiteSaving] = useState(false)
  const [pagesSaving, setPagesSaving] = useState(false)
  const [accountSaving, setAccountSaving] = useState(false)
  const [socialBusy, setSocialBusy] = useState(false)
  const [analyticsBusy, setAnalyticsBusy] = useState(false)
  const busy = siteSaving || pagesSaving || accountSaving || socialBusy || analyticsBusy

  // === Dirty tracking from sections ===
  const [siteDirty, setSiteDirty] = useState(false)
  const [pagesDirty, setPagesDirty] = useState(false)
  const [accountDirty, setAccountDirty] = useState(false)
  const anyDirty = siteDirty || pagesDirty || accountDirty

  useUnsavedChanges(anyDirty)

  useEffect(() => {
    setActiveTab(initialTab)
  }, [initialTab])

  // === Render guard ===
  if (!isReady) {
    return null
  }

  if (loading) {
    return <LoadingSpinner />
  }

  if (loadError !== null) {
    return (
      <div className="text-center py-24">
        <p className="text-red-600 dark:text-red-400">{loadError}</p>
        <Link to="/" className="text-accent text-sm hover:underline mt-4 inline-block">
          Back to home
        </Link>
      </div>
    )
  }

  function handleTabSwitch(key: AdminTabKey) {
    if (anyDirty) {
      const leave = window.confirm('You have unsaved changes. Are you sure you want to leave?')
      if (!leave) return
      setSiteDirty(false)
      setPagesDirty(false)
      setAccountDirty(false)
    }
    setActiveTab(key)
  }

  return (
    <div className="animate-fade-in">
      <div className="mb-6">
        <BackLink to="/" />
      </div>

      <div className="flex items-center gap-3 mb-8">
        <Settings size={20} className="text-accent" />
        <h1 className="font-display text-3xl text-ink">Admin Panel</h1>
      </div>

      <div className="flex border-b border-border mb-8">
        {ADMIN_TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => handleTabSwitch(tab.key)}
            disabled={busy}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
              activeTab === tab.key
                ? 'border-accent text-accent'
                : 'border-transparent text-muted hover:text-ink hover:border-border-dark'
            } disabled:opacity-50 disabled:cursor-not-allowed`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === 'settings' && (
        <SiteSettingsSection
          initialSettings={siteSettings}
          busy={busy}
          onSaving={setSiteSaving}
          onSavedSettings={(s) => { setSiteSettingsOverride(s) }}
          onDirtyChange={setSiteDirty}
        />
      )}
      {activeTab === 'pages' && (
        <PagesSection
          initialPages={pages}
          busy={busy}
          onSaving={setPagesSaving}
          onPagesChange={(p) => { setPagesOverride(p) }}
          onDirtyChange={setPagesDirty}
        />
      )}
      {activeTab === 'account' && (
        <AccountSection busy={busy} passwordChangeDisabled={siteSettings.password_change_disabled} onSaving={setAccountSaving} onDirtyChange={setAccountDirty} />
      )}
      {activeTab === 'social' && (
        <SocialAccountsPanel busy={busy} onBusyChange={setSocialBusy} />
      )}
      {activeTab === 'analytics' && (
        <Suspense fallback={<LoadingSpinner />}>
          <AnalyticsPanel busy={busy} onBusyChange={setAnalyticsBusy} />
        </Suspense>
      )}
    </div>
  )
}
