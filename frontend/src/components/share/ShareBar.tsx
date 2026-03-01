import { useState } from 'react'
import { Check, Link, Mail, Share2, X as XIcon } from 'lucide-react'

import PlatformIcon from '@/components/crosspost/PlatformIcon'

import MastodonSharePrompt from './MastodonSharePrompt'
import {
  canNativeShare,
  copyToClipboard,
  getValidMastodonInstance,
  getShareText,
  getShareUrl,
  nativeShare,
  SHARE_PLATFORMS,
} from './shareUtils'

interface ShareBarProps {
  title: string
  author: string | null
  url: string
}

export default function ShareBar({ title, author, url }: ShareBarProps) {
  const [showMastodonPrompt, setShowMastodonPrompt] = useState(false)
  const [copied, setCopied] = useState(false)
  const [copyFailed, setCopyFailed] = useState(false)

  const shareText = getShareText(title, author, url)

  function handlePlatformClick(platformId: string) {
    if (platformId === 'mastodon') {
      const instance = getValidMastodonInstance()
      if (instance !== null) {
        const shareUrl = getShareUrl('mastodon', shareText, url, title, instance)
        window.open(shareUrl, '_blank', 'noopener,noreferrer')
      } else {
        setShowMastodonPrompt(true)
      }
      return
    }

    const shareUrl = getShareUrl(platformId, shareText, url, title)
    if (shareUrl !== '') {
      window.open(shareUrl, '_blank', 'noopener,noreferrer')
    }
  }

  function handleEmailClick() {
    const emailUrl = getShareUrl('email', shareText, url, title)
    window.open(emailUrl, '_self')
  }

  async function handleCopy() {
    const success = await copyToClipboard(url)
    if (success) {
      setCopied(true)
      setTimeout(() => {
        setCopied(false)
      }, 2000)
    } else {
      setCopyFailed(true)
      setTimeout(() => {
        setCopyFailed(false)
      }, 2000)
    }
  }

  async function handleNativeShare() {
    try {
      await nativeShare(title, shareText, url)
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        return
      }
      // Non-cancellation share failure — no action needed
    }
  }

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
