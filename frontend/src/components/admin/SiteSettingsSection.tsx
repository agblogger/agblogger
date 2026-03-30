import { useEffect, useMemo, useState } from 'react'
import { Settings, Save } from 'lucide-react'

import AlertBanner from '@/components/AlertBanner'
import { HTTPError } from '@/api/client'
import type { AdminSiteSettings } from '@/api/client'
import { updateAdminSiteSettings } from '@/api/admin'
import TimezoneCombobox from './TimezoneCombobox'
import { refreshSiteConfig } from '@/stores/siteStore'

interface SiteSettingsSectionProps {
  initialSettings: AdminSiteSettings
  busy: boolean
  onSaving: (saving: boolean) => void
  onSavedSettings: (settings: AdminSiteSettings) => void
  onDirtyChange: (dirty: boolean) => void
}

function normalizeSiteSettings(
  settings: Partial<AdminSiteSettings> | AdminSiteSettings | null | undefined,
): AdminSiteSettings {
  return {
    title: settings?.title ?? '',
    description: settings?.description ?? '',
    timezone: settings?.timezone ?? '',
    password_change_disabled: settings?.password_change_disabled ?? false,
  }
}

export default function SiteSettingsSection({
  initialSettings,
  busy,
  onSaving,
  onSavedSettings,
  onDirtyChange,
}: SiteSettingsSectionProps) {
  const [siteSettings, setSiteSettings] = useState<AdminSiteSettings>(
    normalizeSiteSettings(initialSettings),
  )
  const [siteError, setSiteError] = useState<string | null>(null)
  const [siteSuccess, setSiteSuccess] = useState<string | null>(null)
  const [savingSite, setSavingSite] = useState(false)

  useEffect(() => { onSaving(savingSite) }, [savingSite, onSaving])

  const normalizedInitial = useMemo(() => normalizeSiteSettings(initialSettings), [initialSettings])

  const isDirty =
    siteSettings.title !== normalizedInitial.title ||
    siteSettings.description !== normalizedInitial.description ||
    siteSettings.timezone !== normalizedInitial.timezone

  useEffect(() => { onDirtyChange(isDirty) }, [isDirty, onDirtyChange])
  useEffect(() => { return () => { onDirtyChange(false) } }, [onDirtyChange])

  useEffect(() => {
    setSiteSettings(normalizeSiteSettings(initialSettings))
  }, [initialSettings])

  async function handleSaveSiteSettings() {
    if (!siteSettings.title.trim()) {
      setSiteError('Title is required.')
      return
    }
    setSavingSite(true)
    setSiteError(null)
    setSiteSuccess(null)
    try {
      const updated = normalizeSiteSettings(await updateAdminSiteSettings(siteSettings))
      setSiteSettings(updated)
      onSavedSettings(updated)
      setSiteSuccess('Settings saved.')
      refreshSiteConfig()
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
        <AlertBanner variant="error" className="mb-4">{siteError}</AlertBanner>
      )}
      {siteSuccess !== null && (
        <AlertBanner variant="success" className="mb-4">{siteSuccess}</AlertBanner>
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
