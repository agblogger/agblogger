import { Check, Link, Mail, Share2, X as XIcon } from 'lucide-react'

import PlatformIcon from '@/components/crosspost/PlatformIcon'

import MastodonSharePrompt from './MastodonSharePrompt'
import { canNativeShare, SHARE_PLATFORMS } from './shareUtils'
import { useShareHandlers } from './useShareHandlers'

interface ShareDropdownContentProps {
  title: string
  author: string | null
  url: string
  onClose: () => void
}

export default function ShareDropdownContent({
  title,
  author,
  url,
  onClose,
}: ShareDropdownContentProps) {
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
  } = useShareHandlers(title, author, url, onClose)

  if (showMastodonPrompt) {
    return (
      <MastodonSharePrompt
        shareText={shareText}
        onClose={() => {
          setShowMastodonPrompt(false)
          onClose()
        }}
      />
    )
  }

  return (
    <div className="space-y-0.5">
      {canNativeShare() && (
        <>
          <button
            onClick={() => {
              handleNativeShare()
                .then(() => {
                  onClose()
                })
                .catch(() => {})
            }}
            aria-label="Share via device"
            className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm
                     text-muted transition-colors hover:bg-paper-warm hover:text-ink"
          >
            <Share2 size={16} />
            <span>Share via device</span>
          </button>
          <div className="my-1 border-t border-border" />
        </>
      )}
      {SHARE_PLATFORMS.map((platform) => (
        <button
          key={platform.id}
          onClick={() => {
            handlePlatformClick(platform.id)
          }}
          aria-label={platform.label}
          className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm
                   text-muted transition-colors hover:bg-paper-warm hover:text-ink"
        >
          <PlatformIcon platform={platform.id} size={16} />
          <span>{platform.label.replace('Share on ', '')}</span>
        </button>
      ))}
      <div className="my-1 border-t border-border" />
      <button
        onClick={handleEmailClick}
        aria-label="Share via email"
        className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm
                 text-muted transition-colors hover:bg-paper-warm hover:text-ink"
      >
        <Mail size={16} />
        <span>Email</span>
      </button>
      <button
        onClick={() => void handleCopy()}
        aria-label="Copy link"
        className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm
                 text-muted transition-colors hover:bg-paper-warm hover:text-ink"
      >
        {copied ? (
          <>
            <Check size={16} className="text-green-600 dark:text-green-400" />
            <span className="text-green-600 dark:text-green-400">Copied!</span>
          </>
        ) : copyFailed ? (
          <>
            <XIcon size={16} className="text-red-600 dark:text-red-400" />
            <span className="text-red-600 dark:text-red-400">Copy failed</span>
          </>
        ) : (
          <>
            <Link size={16} />
            <span>Copy link</span>
          </>
        )}
      </button>
    </div>
  )
}
