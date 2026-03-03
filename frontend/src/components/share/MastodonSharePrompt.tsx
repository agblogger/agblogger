import { useState } from 'react'

import {
  getMastodonInstance,
  getShareUrl,
  isValidHostname,
  setMastodonInstance,
  stripProtocol,
} from './shareUtils'

interface MastodonSharePromptProps {
  shareText: string
  onClose: () => void
}

export default function MastodonSharePrompt({ shareText, onClose }: MastodonSharePromptProps) {
  const [instance, setInstance] = useState(getMastodonInstance() ?? '')
  const [error, setError] = useState<string | null>(null)

  function handleShare() {
    const trimmed = instance.trim()
    if (trimmed === '') return
    if (!isValidHostname(trimmed)) {
      setError('Invalid instance hostname')
      return
    }
    const hostname = stripProtocol(trimmed)
    setMastodonInstance(hostname)
    const url = getShareUrl('mastodon', shareText, '', '', hostname)
    window.open(url, '_blank', 'noopener,noreferrer')
    onClose()
  }

  return (
    <div className="animate-fade-in space-y-2 rounded-lg border border-border bg-paper-warm p-3">
      <label htmlFor="mastodon-instance" className="text-xs font-medium text-muted">
        Mastodon instance
      </label>
      <div className="flex gap-2">
        <input
          id="mastodon-instance"
          type="text"
          value={instance}
          onChange={(e) => {
            setInstance(e.target.value)
            setError(null)
          }}
          placeholder="mastodon.social"
          className="flex-1 rounded-lg border border-border bg-paper px-2.5 py-1.5 text-sm
                   focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent/20"
          onKeyDown={(e) => {
            if (e.key === 'Enter') handleShare()
          }}
        />
        <button
          onClick={handleShare}
          disabled={instance.trim() === ''}
          className="rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-white
                   transition-colors hover:bg-accent-light disabled:opacity-50"
        >
          Share
        </button>
        <button
          onClick={onClose}
          className="rounded-lg border border-border px-3 py-1.5 text-sm font-medium
                   text-muted transition-colors hover:text-ink"
        >
          Cancel
        </button>
      </div>
      {error !== null && <p className="text-xs text-red-600 dark:text-red-400">{error}</p>}
    </div>
  )
}
