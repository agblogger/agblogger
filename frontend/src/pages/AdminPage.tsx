import { useEffect, useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { Settings, ArrowLeft } from 'lucide-react'

import { useAuthStore } from '@/stores/authStore'
import LoadingSpinner from '@/components/LoadingSpinner'
import { HTTPError } from '@/api/client'
import type { AdminSiteSettings, AdminPageConfig } from '@/api/client'
import { fetchAdminSiteSettings, fetchAdminPages } from '@/api/admin'
import SiteSettingsSection from '@/components/admin/SiteSettingsSection'
import PagesSection from '@/components/admin/PagesSection'
import PasswordSection from '@/components/admin/PasswordSection'
import SocialAccountsPanel from '@/components/crosspost/SocialAccountsPanel'

export default function AdminPage() {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const isInitialized = useAuthStore((s) => s.isInitialized)

  // === Loading state ===
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  // === Tab navigation ===
  const [activeTab, setActiveTab] = useState<'settings' | 'pages' | 'password' | 'social'>('settings')

  // === Initial data ===
  const [siteSettings, setSiteSettings] = useState<AdminSiteSettings>({
    title: '',
    description: '',
    default_author: '',
    timezone: '',
  })
  const [pages, setPages] = useState<AdminPageConfig[]>([])

  // === Busy tracking from sections ===
  const [siteSaving, setSiteSaving] = useState(false)
  const [pagesSaving, setPagesSaving] = useState(false)
  const [passwordSaving, setPasswordSaving] = useState(false)
  const [socialBusy, setSocialBusy] = useState(false)
  const busy = siteSaving || pagesSaving || passwordSaving || socialBusy

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
    void (async () => {
      setLoading(true)
      setLoadError(null)
      try {
        const [settings, pagesResp] = await Promise.all([
          fetchAdminSiteSettings(),
          fetchAdminPages(),
        ])
        setSiteSettings(settings)
        setPages(pagesResp.pages)
      } catch (err: unknown) {
        if (err instanceof HTTPError && err.response.status === 401) {
          setLoadError('Session expired. Please log in again.')
        } else {
          setLoadError('Failed to load admin data. Please try again later.')
        }
      } finally {
        setLoading(false)
      }
    })()
  }, [isInitialized, user?.is_admin])

  // === Render guards ===
  if (!isInitialized || !user) {
    return null
  }

  if (!user.is_admin) {
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

      <div className="flex border-b border-border mb-8">
        {([
          { key: 'settings', label: 'Settings' },
          { key: 'pages', label: 'Pages' },
          { key: 'password', label: 'Password' },
          { key: 'social', label: 'Social' },
        ] as const).map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
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
          onSavedSettings={setSiteSettings}
        />
      )}
      {activeTab === 'pages' && (
        <PagesSection
          initialPages={pages}
          busy={busy}
          onSaving={setPagesSaving}
          onPagesChange={setPages}
        />
      )}
      {activeTab === 'password' && (
        <PasswordSection busy={busy} onSaving={setPasswordSaving} />
      )}
      {activeTab === 'social' && (
        <SocialAccountsPanel busy={busy} onBusyChange={setSocialBusy} />
      )}
    </div>
  )
}
