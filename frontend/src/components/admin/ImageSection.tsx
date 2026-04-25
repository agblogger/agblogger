import { useEffect, useState } from 'react'
import { Upload, Trash2 } from 'lucide-react'

import AlertBanner from '@/components/AlertBanner'
import { HTTPError } from '@/api/client'
import type { AdminSiteSettings } from '@/api/client'
import { removeAdminImage, uploadAdminImage } from '@/api/admin'
import { refreshSiteConfig } from '@/stores/siteStore'

interface ImageSectionProps {
  initialImage: string | null
  busy: boolean
  onSavedSettings: (settings: AdminSiteSettings) => void
}

const PUBLIC_PATHS_BY_EXT: Record<string, string> = {
  png: '/image.png',
  jpg: '/image.jpg',
  jpeg: '/image.jpg',
  webp: '/image.webp',
  gif: '/image.gif',
}

function publicImageUrl(image: string): string | null {
  const ext = image.split('.').pop()?.toLowerCase()
  if (ext === undefined) return null
  return PUBLIC_PATHS_BY_EXT[ext] ?? null
}

export default function ImageSection({
  initialImage,
  busy,
  onSavedSettings,
}: ImageSectionProps) {
  const [image, setImage] = useState<string | null>(initialImage)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setImage(initialImage)
  }, [initialImage])

  const isDisabled = busy || loading

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    e.target.value = ''
    setLoading(true)
    setError(null)
    try {
      const updated = await uploadAdminImage(file)
      setImage(updated.image)
      onSavedSettings(updated)
      refreshSiteConfig()
    } catch (err) {
      if (err instanceof HTTPError && err.response.status === 413) {
        setError('File too large. Maximum size is 5 MB.')
      } else if (err instanceof HTTPError && err.response.status === 422) {
        setError('Unsupported file type. Use PNG, JPEG, WebP, or GIF.')
      } else {
        setError('Failed to upload image. Please try again.')
      }
    } finally {
      setLoading(false)
    }
  }

  async function handleRemove() {
    setLoading(true)
    setError(null)
    try {
      const updated = await removeAdminImage()
      setImage(null)
      onSavedSettings(updated)
      refreshSiteConfig()
    } catch (err) {
      if (err instanceof HTTPError && err.response.status === 401) {
        setError('Session expired. Please refresh and log in again.')
      } else if (err instanceof HTTPError) {
        setError(`Failed to remove image (${err.response.status.toString()}). Please try again.`)
      } else {
        setError('Failed to remove image. Please try again.')
      }
    } finally {
      setLoading(false)
    }
  }

  const filename = image !== null ? (image.split('/').pop() ?? image) : null
  const publicPath = image !== null ? publicImageUrl(image) : null
  const previewSrc = publicPath !== null ? `${publicPath}?v=${encodeURIComponent(image ?? '')}` : null

  return (
    <div className="mt-5 border-t border-border pt-5">
      <div className="text-xs font-medium text-muted mb-3 uppercase tracking-wide">Website image</div>

      {error !== null && (
        <AlertBanner variant="error" className="mb-3">{error}</AlertBanner>
      )}

      {image === null ? (
        <div>
          <p className="text-xs text-muted italic mb-3">
            No image set — link previews on Facebook, WhatsApp, and other platforms will not include
            a thumbnail when a post has no inline image.
          </p>
          <label
            className={`inline-flex items-center gap-2 px-3 py-2 border border-dashed border-border
                        rounded-lg text-xs text-muted bg-paper-warm cursor-pointer
                        hover:border-accent hover:text-accent transition-colors
                        ${isDisabled ? 'opacity-50 pointer-events-none' : ''}`}
          >
            <Upload size={13} />
            {loading ? 'Uploading...' : 'Upload image (PNG, JPEG, WebP, GIF)'}
            <input
              type="file"
              accept=".png,.jpg,.jpeg,.webp,.gif,image/png,image/jpeg,image/webp,image/gif"
              className="sr-only"
              disabled={isDisabled}
              onChange={(e) => void handleFileChange(e)}
            />
          </label>
        </div>
      ) : (
        <div>
          <div className="flex items-center gap-3">
            <div className="w-16 h-10 border border-border rounded-lg bg-paper-warm
                            flex items-center justify-center overflow-hidden flex-shrink-0">
              {previewSrc !== null && (
                <img
                  src={previewSrc}
                  alt="Current website image"
                  className="w-full h-full object-cover"
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
                  accept=".png,.jpg,.jpeg,.webp,.gif,image/png,image/jpeg,image/webp,image/gif"
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
            Used as the preview image when your blog or a post (without an inline image) is shared on
            Facebook, WhatsApp, Twitter, Slack, and other platforms. Recommended size: 1200×630.
          </p>
        </div>
      )}
    </div>
  )
}
