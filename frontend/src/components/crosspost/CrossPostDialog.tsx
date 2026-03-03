import { useEffect, useMemo, useState } from 'react'

import { crossPost } from '@/api/crosspost'
import type { SocialAccount, CrossPostResult } from '@/api/crosspost'
import PlatformIcon from '@/components/crosspost/PlatformIcon'
import { buildDefaultText } from '@/components/crosspost/crosspostText'

const CHAR_LIMITS: Record<string, number> = {
  bluesky: 300,
  x: 280,
  mastodon: 500,
}

interface CrossPostDialogProps {
  open: boolean
  onClose: () => void
  accounts: SocialAccount[]
  postPath: string
  postTitle: string
  postExcerpt: string
  postLabels: string[]
  initialPlatforms?: string[]
}

export default function CrossPostDialog({
  open,
  onClose,
  accounts,
  postPath,
  postTitle,
  postExcerpt,
  postLabels,
  initialPlatforms,
}: CrossPostDialogProps) {
  const [text, setText] = useState('')
  const [selectedPlatforms, setSelectedPlatforms] = useState<Set<string>>(new Set())
  const [posting, setPosting] = useState(false)
  const [results, setResults] = useState<CrossPostResult[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  const accountPlatforms = useMemo(
    () => accounts.map((a) => a.platform).join(','),
    [accounts],
  )

  // Reset state when dialog opens
  useEffect(() => {
    if (open) {
      setText(buildDefaultText(postTitle, postExcerpt, postLabels, postPath))
      if (initialPlatforms) {
        setSelectedPlatforms(new Set(initialPlatforms))
      } else {
        setSelectedPlatforms(new Set(accountPlatforms.split(',').filter(Boolean)))
      }
      setResults(null)
      setError(null)
      setPosting(false)
    }
  }, [open, postTitle, postExcerpt, postLabels, postPath, accountPlatforms, initialPlatforms])

  if (!open) return null

  function handleTogglePlatform(platform: string) {
    setSelectedPlatforms((prev) => {
      const next = new Set(prev)
      if (next.has(platform)) {
        next.delete(platform)
      } else {
        next.add(platform)
      }
      return next
    })
  }

  const isOverLimit = Array.from(selectedPlatforms).some((platform) => {
    const limit = CHAR_LIMITS[platform]
    return limit !== undefined && text.length > limit
  })

  const canPost = selectedPlatforms.size > 0 && !isOverLimit && !posting

  async function handlePost() {
    setPosting(true)
    setError(null)
    try {
      const resultData = await crossPost(postPath, Array.from(selectedPlatforms), text)
      setResults(resultData)
    } catch {
      setError('Failed to cross-post. Please try again.')
    } finally {
      setPosting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="bg-paper border border-border rounded-xl shadow-xl p-6 max-w-lg w-full mx-4 animate-fade-in">
        {results !== null ? (
          // Results view
          <>
            <h2 className="font-display text-xl text-ink mb-4">Cross-Post Results</h2>
            <div className="space-y-3 mb-6">
              {results.map((result) => (
                <div
                  key={`${result.platform}-${result.id}`}
                  className="flex items-center gap-3 px-4 py-3 border border-border rounded-lg"
                >
                  <PlatformIcon platform={result.platform} size={18} className="text-muted" />
                  <span className="text-sm font-medium text-ink flex-1">{result.platform}</span>
                  {result.status === 'posted' ? (
                    <span className="px-2 py-0.5 text-xs font-medium bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 rounded-full">
                      Posted
                    </span>
                  ) : (
                    <div className="flex items-center gap-2">
                      <span className="px-2 py-0.5 text-xs font-medium bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400 rounded-full">
                        Failed
                      </span>
                      {result.error !== null && (
                        <span className="text-xs text-red-600 dark:text-red-400">{result.error}</span>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
            <div className="flex justify-end">
              <button
                onClick={onClose}
                className="px-4 py-2 text-sm font-medium text-muted hover:text-ink
                         border border-border rounded-lg transition-colors"
              >
                Close
              </button>
            </div>
          </>
        ) : (
          // Form view
          <>
            <h2 className="font-display text-xl text-ink mb-4">Cross-Post</h2>

            {error !== null && (
              <div className="mb-4 text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800/40 rounded-lg px-4 py-3">
                {error}
              </div>
            )}

            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              disabled={posting}
              aria-label="Cross-post text"
              className="w-full min-h-[120px] p-3 bg-paper-warm border border-border rounded-lg
                       font-mono text-sm leading-relaxed text-ink resize-y
                       focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/20
                       disabled:opacity-50"
            />

            {/* Character counters */}
            <div className="flex gap-4 mt-2 mb-4">
              {accounts
                .filter((a) => selectedPlatforms.has(a.platform))
                .map((account) => {
                  const limit = CHAR_LIMITS[account.platform]
                  if (limit === undefined) return null
                  const isOver = text.length > limit
                  return (
                    <div
                      key={account.platform}
                      className={`flex items-center gap-1.5 text-xs ${isOver ? 'text-red-600 dark:text-red-400' : 'text-muted'}`}
                    >
                      <PlatformIcon platform={account.platform} size={14} />
                      <span>
                        {text.length}/{limit}
                      </span>
                    </div>
                  )
                })}
            </div>

            {/* Platform checkboxes */}
            <div className="space-y-2 mb-6">
              {accounts.map((account) => (
                <label
                  key={account.id}
                  className="flex items-center gap-3 cursor-pointer"
                >
                  <input
                    type="checkbox"
                    checked={selectedPlatforms.has(account.platform)}
                    onChange={() => handleTogglePlatform(account.platform)}
                    disabled={posting}
                    className="rounded border-border text-accent focus:ring-accent/20 disabled:opacity-50"
                  />
                  <PlatformIcon platform={account.platform} size={16} className="text-muted" />
                  <span className="text-sm text-ink">
                    {account.account_name ?? account.platform}
                  </span>
                </label>
              ))}
            </div>

            {/* Action buttons */}
            <div className="flex justify-end gap-3">
              <button
                onClick={onClose}
                disabled={posting}
                className="px-4 py-2 text-sm font-medium text-muted hover:text-ink
                         border border-border rounded-lg transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={() => void handlePost()}
                disabled={!canPost}
                className="px-4 py-2 text-sm font-medium text-white bg-accent hover:bg-accent-light
                         rounded-lg transition-colors disabled:opacity-50"
              >
                {posting ? 'Posting...' : 'Post'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
