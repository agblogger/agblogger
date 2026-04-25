import type { AdminSiteSettings } from '@/api/client'
import { removeAdminImage, uploadAdminImage } from '@/api/admin'

import SiteAssetSection, { type SiteAssetAdapter } from './SiteAssetSection'

interface ImageSectionProps {
  initialImage: string | null
  busy: boolean
  onSavedSettings: (settings: AdminSiteSettings) => void
}

// Keep these in sync with backend/services/upload_limits.py SITE_IMAGE_FORMATS.
// `.jpeg` collapses to /image.jpg because the backend canonicalizes JPEG to .jpg
// on disk; both extensions resolve to the same public route.
const PUBLIC_PATHS_BY_EXT: Record<string, string> = {
  png: '/image.png',
  jpg: '/image.jpg',
  jpeg: '/image.jpg',
  webp: '/image.webp',
  gif: '/image.gif',
}

function imagePublicUrl(image: string): string | null {
  const ext = image.split('.').pop()?.toLowerCase()
  if (ext === undefined) return null
  return PUBLIC_PATHS_BY_EXT[ext] ?? null
}

const IMAGE_ADAPTER: SiteAssetAdapter = {
  upload: uploadAdminImage,
  remove: removeAdminImage,
  selectAsset: (s) => s.image,
  previewUrl: imagePublicUrl,
}

export default function ImageSection({
  initialImage,
  busy,
  onSavedSettings,
}: ImageSectionProps) {
  return (
    <SiteAssetSection
      heading="Website image"
      emptyHint="No image set — link previews on Facebook, WhatsApp, and other platforms will not include a thumbnail when a post has no inline image."
      footerHint="Used as the preview image when your blog or a post (without an inline image) is shared on Facebook, WhatsApp, Twitter, Slack, and other platforms. Recommended size: 1200×630."
      uploadPrompt="Upload image (PNG, JPEG, WebP, GIF)"
      accept=".png,.jpg,.jpeg,.webp,.gif,image/png,image/jpeg,image/webp,image/gif"
      previewAlt="Current website image"
      previewBoxClassName="w-16 h-10"
      previewImgClassName="object-cover"
      fileTooLargeMsg="File too large. Maximum size is 5 MB."
      unsupportedTypeMsg="Unsupported file type. Use PNG, JPEG, WebP, or GIF."
      removeFailureLabel="image"
      uploadFailureLabel="image"
      initialAsset={initialImage}
      busy={busy}
      adapter={IMAGE_ADAPTER}
      onSavedSettings={onSavedSettings}
    />
  )
}
