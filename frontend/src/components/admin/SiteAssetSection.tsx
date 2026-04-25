import { useEffect, useState } from 'react'
import { Upload, Trash2 } from 'lucide-react'

import AlertBanner from '@/components/AlertBanner'
import { HTTPError } from '@/api/client'
import type { AdminSiteSettings } from '@/api/client'
import { refreshSiteConfig } from '@/stores/siteStore'

export interface SiteAssetSectionProps {
  heading: string
  emptyHint: string
  footerHint: string
  uploadPrompt: string
  accept: string
  previewAlt: string
  previewBoxClassName: string
  previewImgClassName: string
  fileTooLargeMsg: string
  unsupportedTypeMsg: string
  removeFailureLabel: string
  uploadFailureLabel: string
  initialAsset: string | null
  busy: boolean
  selectAsset: (settings: AdminSiteSettings) => string | null
  upload: (file: File) => Promise<AdminSiteSettings>
  remove: () => Promise<AdminSiteSettings>
  previewUrl: (asset: string) => string | null
  onSavedSettings: (settings: AdminSiteSettings) => void
}

export default function SiteAssetSection({
  heading,
  emptyHint,
  footerHint,
  uploadPrompt,
  accept,
  previewAlt,
  previewBoxClassName,
  previewImgClassName,
  fileTooLargeMsg,
  unsupportedTypeMsg,
  removeFailureLabel,
  uploadFailureLabel,
  initialAsset,
  busy,
  selectAsset,
  upload,
  remove,
  previewUrl,
  onSavedSettings,
}: SiteAssetSectionProps) {
  const [asset, setAsset] = useState<string | null>(initialAsset)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setAsset(initialAsset)
  }, [initialAsset])

  const isDisabled = busy || loading

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    e.target.value = ''
    setLoading(true)
    setError(null)
    try {
      const updated = await upload(file)
      setAsset(selectAsset(updated))
      onSavedSettings(updated)
      refreshSiteConfig()
    } catch (err) {
      if (err instanceof HTTPError && err.response.status === 413) {
        setError(fileTooLargeMsg)
      } else if (err instanceof HTTPError && err.response.status === 422) {
        setError(unsupportedTypeMsg)
      } else {
        setError(`Failed to upload ${uploadFailureLabel}. Please try again.`)
      }
    } finally {
      setLoading(false)
    }
  }

  async function handleRemove() {
    setLoading(true)
    setError(null)
    try {
      const updated = await remove()
      setAsset(null)
      onSavedSettings(updated)
      refreshSiteConfig()
    } catch (err) {
      if (err instanceof HTTPError && err.response.status === 401) {
        setError('Session expired. Please refresh and log in again.')
      } else if (err instanceof HTTPError) {
        setError(
          `Failed to remove ${removeFailureLabel} (${err.response.status.toString()}). Please try again.`,
        )
      } else {
        setError(`Failed to remove ${removeFailureLabel}. Please try again.`)
      }
    } finally {
      setLoading(false)
    }
  }

  const filename = asset !== null ? (asset.split('/').pop() ?? asset) : null
  const publicPath = asset !== null ? previewUrl(asset) : null
  const previewSrc =
    asset !== null && publicPath !== null
      ? `${publicPath}?v=${encodeURIComponent(asset)}`
      : null

  return (
    <div className="mt-5 border-t border-border pt-5">
      <div className="text-xs font-medium text-muted mb-3 uppercase tracking-wide">{heading}</div>

      {error !== null && (
        <AlertBanner variant="error" className="mb-3">{error}</AlertBanner>
      )}

      {asset === null ? (
        <div>
          <p className="text-xs text-muted italic mb-3">{emptyHint}</p>
          <label
            className={`inline-flex items-center gap-2 px-3 py-2 border border-dashed border-border
                        rounded-lg text-xs text-muted bg-paper-warm cursor-pointer
                        hover:border-accent hover:text-accent transition-colors
                        ${isDisabled ? 'opacity-50 pointer-events-none' : ''}`}
          >
            <Upload size={13} />
            {loading ? 'Uploading...' : uploadPrompt}
            <input
              type="file"
              accept={accept}
              className="sr-only"
              disabled={isDisabled}
              onChange={(e) => void handleFileChange(e)}
            />
          </label>
        </div>
      ) : (
        <div>
          <div className="flex items-center gap-3">
            <div
              className={`${previewBoxClassName} border border-border rounded-lg bg-paper-warm
                          flex items-center justify-center overflow-hidden flex-shrink-0`}
            >
              {previewSrc !== null && (
                <img
                  src={previewSrc}
                  alt={previewAlt}
                  className={`w-full h-full ${previewImgClassName}`}
                />
              )}
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
                  accept={accept}
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
          <p className="text-xs text-muted italic mt-2">{footerHint}</p>
        </div>
      )}
    </div>
  )
}
