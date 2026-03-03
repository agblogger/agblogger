import { useEffect, useState } from 'react'
import { Settings, Save } from 'lucide-react'

import { HTTPError } from '@/api/client'
import type { AdminSiteSettings } from '@/api/client'
import { updateAdminSiteSettings } from '@/api/admin'
import { useSiteStore } from '@/stores/siteStore'

interface SiteSettingsSectionProps {
  initialSettings: AdminSiteSettings
  busy: boolean
  onSaving: (saving: boolean) => void
}

export default function SiteSettingsSection({
  initialSettings,
  busy,
  onSaving,
}: SiteSettingsSectionProps) {
  const [siteSettings, setSiteSettings] = useState<AdminSiteSettings>(initialSettings)
  const [siteError, setSiteError] = useState<string | null>(null)
  const [siteSuccess, setSiteSuccess] = useState<string | null>(null)
  const [savingSite, setSavingSite] = useState(false)

  useEffect(() => { onSaving(savingSite) }, [savingSite, onSaving])

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
  )
}
