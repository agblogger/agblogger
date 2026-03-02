import { Check, Link, Mail, Share2, X as XIcon } from 'lucide-react'

import PlatformIcon from '@/components/crosspost/PlatformIcon'

import MastodonSharePrompt from './MastodonSharePrompt'
import { canNativeShare, SHARE_PLATFORMS } from './shareUtils'
import { useShareHandlers } from './useShareHandlers'

interface ShareBarProps {
  title: string
  author: string | null
  url: string
}

export default function ShareBar({ title, author, url }: ShareBarProps) {
  const {
    shareText,
    copied,
    copyFailed,
    showMastodonPrompt,
    setShowMastodonPrompt,
    handlePlatformClick,
    handleEmailClick,
    handleCopy,
    handleNativeShare,
  } = useShareHandlers(title, author, url)

  return (
    <div className="mt-10 border-t border-border pt-6">
      <div className="flex flex-wrap items-center gap-1">
        {canNativeShare() && (
          <div className="tooltip-wrap">
            <button
              onClick={() => void handleNativeShare()}
              aria-label="Share via device"
              className="rounded-lg p-2 text-muted transition-colors hover:bg-paper-warm hover:text-ink"
            >
              <Share2 size={18} />
            </button>
            <span role="tooltip">Share</span>
          </div>
        )}

        {SHARE_PLATFORMS.map((platform) => (
          <div key={platform.id} className="tooltip-wrap">
            <button
              onClick={() => {
                handlePlatformClick(platform.id)
              }}
              aria-label={platform.label}
              className="rounded-lg p-2 text-muted transition-colors hover:bg-paper-warm hover:text-ink"
            >
              <PlatformIcon platform={platform.id} size={18} />
            </button>
            <span role="tooltip">{platform.label}</span>
          </div>
        ))}

        <div className="tooltip-wrap">
          <button
            onClick={handleEmailClick}
            aria-label="Share via email"
            className="rounded-lg p-2 text-muted transition-colors hover:bg-paper-warm hover:text-ink"
          >
            <Mail size={18} />
          </button>
          <span role="tooltip">Share via email</span>
        </div>

        <div className="tooltip-wrap">
          <button
            onClick={() => void handleCopy()}
            aria-label="Copy link"
            className="rounded-lg p-2 text-muted transition-colors hover:bg-paper-warm hover:text-ink"
          >
            {copied ? (
              <Check size={18} className="text-green-600" />
            ) : copyFailed ? (
              <XIcon size={18} className="text-red-600" />
            ) : (
              <Link size={18} />
            )}
          </button>
          <span role="tooltip">Copy link</span>
        </div>

        {copied && (
          <span className="animate-fade-in text-xs font-medium text-green-600">Copied!</span>
        )}
        {copyFailed && (
          <span className="animate-fade-in text-xs font-medium text-red-600">Copy failed</span>
        )}
      </div>

      {showMastodonPrompt && (
        <div className="mt-3">
          <MastodonSharePrompt
            shareText={shareText}
            onClose={() => {
              setShowMastodonPrompt(false)
            }}
          />
        </div>
      )}
    </div>
  )
}
