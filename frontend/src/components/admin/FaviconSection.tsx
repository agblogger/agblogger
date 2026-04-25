import { useEffect, useState } from 'react'
import { Upload, Trash2 } from 'lucide-react'

import AlertBanner from '@/components/AlertBanner'
import { HTTPError } from '@/api/client'
import type { AdminSiteSettings } from '@/api/client'
import { removeAdminFavicon, uploadAdminFavicon } from '@/api/admin'
import { refreshSiteConfig } from '@/stores/siteStore'

interface FaviconSectionProps {
  initialFavicon: string | null
  busy: boolean
  onSavedSettings: (settings: AdminSiteSettings) => void
}

export default function FaviconSection({
  initialFavicon,
  busy,
  onSavedSettings,
}: FaviconSectionProps) {
  const [favicon, setFavicon] = useState<string | null>(initialFavicon)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setFavicon(initialFavicon)
  }, [initialFavicon])

  const isDisabled = busy || loading

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    e.target.value = ''
    setLoading(true)
    setError(null)
    try {
      const updated = await uploadAdminFavicon(file)
      setFavicon(updated.favicon)
      onSavedSettings(updated)
      refreshSiteConfig()
    } catch (err) {
      if (err instanceof HTTPError && err.response.status === 413) {
        setError('File too large. Maximum size is 2 MB.')
      } else if (err instanceof HTTPError && err.response.status === 422) {
        setError('Unsupported file type. Use PNG, ICO, SVG, or WebP.')
      } else {
        setError('Failed to upload favicon. Please try again.')
      }
    } finally {
      setLoading(false)
    }
  }

  async function handleRemove() {
    setLoading(true)
    setError(null)
    try {
      const updated = await removeAdminFavicon()
      setFavicon(null)
      onSavedSettings(updated)
      refreshSiteConfig()
    } catch (err) {
      if (err instanceof HTTPError && err.response.status === 401) {
        setError('Session expired. Please refresh and log in again.')
      } else if (err instanceof HTTPError) {
        setError(`Failed to remove favicon (${err.response.status}). Please try again.`)
      } else {
        setError('Failed to remove favicon. Please try again.')
      }
    } finally {
      setLoading(false)
    }
  }

  const filename = favicon !== null ? (favicon.split('/').pop() ?? favicon) : null

  return (
    <div className="mt-5 border-t border-border pt-5">
      <div className="text-xs font-medium text-muted mb-3 uppercase tracking-wide">Blog icon</div>

      {error !== null && (
        <AlertBanner variant="error" className="mb-3">{error}</AlertBanner>
      )}

      {favicon === null ? (
        <div>
          <p className="text-xs text-muted italic mb-3">
            No icon set — browsers will show a blank tab icon.
          </p>
          <label
            className={`inline-flex items-center gap-2 px-3 py-2 border border-dashed border-border
                        rounded-lg text-xs text-muted bg-paper-warm cursor-pointer
                        hover:border-accent hover:text-accent transition-colors
                        ${isDisabled ? 'opacity-50 pointer-events-none' : ''}`}
          >
            <Upload size={13} />
            {loading ? 'Uploading...' : 'Upload image (PNG, ICO, SVG, WebP)'}
            <input
              type="file"
              accept=".png,.ico,.svg,.webp,image/png,image/x-icon,image/svg+xml,image/webp"
              className="sr-only"
              disabled={isDisabled}
              onChange={(e) => void handleFileChange(e)}
            />
          </label>
        </div>
      ) : (
        <div>
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 border border-border rounded-lg bg-paper-warm
                            flex items-center justify-center overflow-hidden flex-shrink-0">
              <img
                src={`/favicon.ico?v=${encodeURIComponent(favicon)}`}
                alt="Current blog icon"
                className="w-full h-full object-contain"
              />
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-xs font-medium text-ink truncate">{filename}</div>
            </div>
            <div className="flex gap-2 flex-shrink-0">
              <label
                className={`inline-flex items-center gap-1.5 px-3 py-1.5 border border-border
                            rounded-md text-xs text-muted bg-paper cursor-pointer
                            hover:border-accent hover:text-accent transition-colors
                            ${isDisabled ? 'opacity-50 pointer-events-none' : ''}`}
              >
                <Upload size={12} />
                {loading ? 'Uploading...' : 'Replace'}
                <input
                  type="file"
                  accept=".png,.ico,.svg,.webp,image/png,image/x-icon,image/svg+xml,image/webp"
                  className="sr-only"
                  disabled={isDisabled}
                  onChange={(e) => void handleFileChange(e)}
                />
              </label>
              <button
                onClick={() => void handleRemove()}
                disabled={isDisabled}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 border border-red-200
                           rounded-md text-xs text-red-500 bg-paper
                           hover:border-red-400 hover:text-red-600 disabled:opacity-50
                           transition-colors"
              >
                <Trash2 size={12} />
                {loading ? 'Removing...' : 'Remove'}
              </button>
            </div>
          </div>
          <p className="text-xs text-muted italic mt-2">
            Shown in browser tabs, bookmarks, and address bar.
          </p>
        </div>
      )}
    </div>
  )
}
