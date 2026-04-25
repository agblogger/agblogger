import type { AdminSiteSettings } from '@/api/client'
import { removeAdminFavicon, uploadAdminFavicon } from '@/api/admin'

import SiteAssetSection, { type SiteAssetAdapter } from './SiteAssetSection'

interface FaviconSectionProps {
  initialFavicon: string | null
  busy: boolean
  onSavedSettings: (settings: AdminSiteSettings) => void
}

const FAVICON_ADAPTER: SiteAssetAdapter = {
  upload: uploadAdminFavicon,
  remove: removeAdminFavicon,
  selectAsset: (s) => s.favicon,
  previewUrl: () => '/favicon.ico',
}

export default function FaviconSection({
  initialFavicon,
  busy,
  onSavedSettings,
}: FaviconSectionProps) {
  return (
    <SiteAssetSection
      heading="Blog icon"
      emptyHint="No icon set — browsers will show a blank tab icon."
      footerHint="Shown in browser tabs, bookmarks, and address bar."
      uploadPrompt="Upload image (PNG, ICO, SVG, WebP)"
      accept=".png,.ico,.svg,.webp,image/png,image/x-icon,image/svg+xml,image/webp"
      previewAlt="Current blog icon"
      previewBoxClassName="w-10 h-10"
      previewImgClassName="object-contain"
      fileTooLargeMsg="File too large. Maximum size is 2 MB."
      unsupportedTypeMsg="Unsupported file type. Use PNG, ICO, SVG, or WebP."
      removeFailureLabel="favicon"
      uploadFailureLabel="favicon"
      initialAsset={initialFavicon}
      busy={busy}
      adapter={FAVICON_ADAPTER}
      onSavedSettings={onSavedSettings}
    />
  )
}
