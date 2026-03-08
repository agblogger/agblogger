import { useEffect, useState } from 'react'
import { Settings, Save } from 'lucide-react'

import { HTTPError } from '@/api/client'
import type { AdminSiteSettings } from '@/api/client'
import { updateAdminSiteSettings, updateDisplayName } from '@/api/admin'
import TimezoneCombobox from './TimezoneCombobox'
import { useSiteStore } from '@/stores/siteStore'
import { useAuthStore } from '@/stores/authStore'

interface SiteSettingsSectionProps {
  initialSettings: AdminSiteSettings
  initialDisplayName: string
  busy: boolean
  onSaving: (saving: boolean) => void
  onSavedSettings: (settings: AdminSiteSettings) => void
}

export default function SiteSettingsSection({
  initialSettings,
  initialDisplayName,
  busy,
  onSaving,
  onSavedSettings,
}: SiteSettingsSectionProps) {
  const [siteSettings, setSiteSettings] = useState<AdminSiteSettings>(initialSettings)
  const [displayName, setDisplayName] = useState(initialDisplayName)
  const [siteError, setSiteError] = useState<string | null>(null)
  const [siteSuccess, setSiteSuccess] = useState<string | null>(null)
  const [savingSite, setSavingSite] = useState(false)

  useEffect(() => { onSaving(savingSite) }, [savingSite, onSaving])
  useEffect(() => {
    setSiteSettings(initialSettings)
  }, [initialSettings])
  useEffect(() => {
    setDisplayName(initialDisplayName)
  }, [initialDisplayName])

  async function handleSaveSiteSettings() {
    if (!siteSettings.title.trim()) {
      setSiteError('Title is required.')
      return
    }
    setSavingSite(true)
    setSiteError(null)
    setSiteSuccess(null)
    try {
      const [updated] = await Promise.all([
        updateAdminSiteSettings(siteSettings),
        updateDisplayName(displayName),
      ])
      setSiteSettings(updated)
      onSavedSettings(updated)
      setSiteSuccess('Settings saved.')
      const user = useAuthStore.getState().user
      if (user) {
        useAuthStore.setState({
          user: { ...user, display_name: displayName.trim() || null },
        })
      }
      useSiteStore.getState().fetchConfig().catch((err: unknown) => { console.warn('Failed to refresh site config', err) })
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

  return (
    <section className="mb-8 p-5 bg-paper border border-border rounded-lg">
      <div className="flex items-center gap-2 mb-4">
        <Settings size={16} className="text-accent" />
        <h2 className="text-sm font-medium text-ink">Settings</h2>
      </div>

      {siteError !== null && (
        <div className="mb-4 text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800/40 rounded-lg px-4 py-3">
          {siteError}
        </div>
      )}
      {siteSuccess !== null && (
        <div className="mb-4 text-sm text-green-700 dark:text-green-400 bg-green-50 dark:bg-green-950/30 border border-green-200 dark:border-green-800/40 rounded-lg px-4 py-3">
          {siteSuccess}
        </div>
      )}

      <div className="space-y-4">
        <div>
          <label htmlFor="display-name" className="block text-xs font-medium text-muted mb-1">
            Name
          </label>
          <input
            id="display-name"
            type="text"
            value={displayName}
            onChange={(e) => {
              setDisplayName(e.target.value)
              setSiteSuccess(null)
            }}
            disabled={busy}
            maxLength={100}
            className="w-full px-3 py-2 bg-paper-warm border border-border rounded-lg
                     text-ink text-sm
                     focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/20
                     disabled:opacity-50"
          />
        </div>

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
          <label htmlFor="site-timezone" className="block text-xs font-medium text-muted mb-1">
            Timezone
          </label>
          <TimezoneCombobox
            value={siteSettings.timezone}
            onChange={(tz) => {
              setSiteSettings({ ...siteSettings, timezone: tz })
              setSiteSuccess(null)
            }}
            disabled={busy}
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
  )
}
