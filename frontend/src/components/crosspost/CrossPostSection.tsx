import { useCallback, useEffect, useState } from 'react'
import { Share2 } from 'lucide-react'

import { fetchCrossPostHistory, fetchSocialAccounts } from '@/api/crosspost'
import type { CrossPostResult, SocialAccount } from '@/api/crosspost'
import type { PostDetail } from '@/api/client'
import CrossPostDialog from '@/components/crosspost/CrossPostDialog'
import CrossPostHistory from '@/components/crosspost/CrossPostHistory'

interface CrossPostSectionProps {
  filePath: string
  post: PostDetail
}

export default function CrossPostSection({ filePath, post }: CrossPostSectionProps) {
  const [historyItems, setHistoryItems] = useState<CrossPostResult[]>([])
  const [historyLoading, setHistoryLoading] = useState(true)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [accounts, setAccounts] = useState<SocialAccount[]>([])
  const [accountsLoading, setAccountsLoading] = useState(true)
  const [accountsError, setAccountsError] = useState<string | null>(null)
  const [showDialog, setShowDialog] = useState(false)

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true)
    setHistoryError(null)
    try {
      const history = await fetchCrossPostHistory(filePath)
      setHistoryItems(history.items)
    } catch {
      setHistoryError('Failed to load cross-post history. Please try again.')
    } finally {
      setHistoryLoading(false)
    }
  }, [filePath])

  useEffect(() => {
    if (post.is_draft) {
      setHistoryLoading(false)
      setAccountsLoading(false)
      setHistoryError(null)
      setAccountsError(null)
      setHistoryItems([])
      setAccounts([])
      return
    }
    void loadHistory()
    void (async () => {
      setAccountsLoading(true)
      setAccountsError(null)
      try {
        const accts = await fetchSocialAccounts()
        setAccounts(accts)
      } catch {
        setAccountsError('Failed to load connected social accounts. Please try again.')
      } finally {
        setAccountsLoading(false)
      }
    })()
  }, [loadHistory, post.is_draft])

  if (post.is_draft) {
    return (
      <section className="mt-10 pt-6 border-t border-border">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-medium text-muted">Cross-posting</h3>
        </div>
        <p className="text-sm text-muted">Publish this draft to enable cross-posting.</p>
      </section>
    )
  }

  function handleDialogClose() {
    setShowDialog(false)
    void loadHistory()
  }

  return (
    <section className="mt-10 pt-6 border-t border-border">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-medium text-muted">Cross-posting</h3>
        {accounts.length > 0 && (
          <button
            onClick={() => setShowDialog(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium
                     text-muted border border-border rounded-lg
                     hover:text-ink hover:bg-paper-warm
                     disabled:opacity-50 transition-colors"
          >
            <Share2 size={14} />
            Cross-post
          </button>
        )}
      </div>
      {historyError !== null && (
        <div className="mb-4 text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800/40 rounded-lg px-4 py-3">
          {historyError}
        </div>
      )}
      {accountsError !== null && (
        <div className="mb-4 text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800/40 rounded-lg px-4 py-3">
          {accountsError}
        </div>
      )}
      <CrossPostHistory items={historyItems} loading={historyLoading} />
      {!accountsLoading && accounts.length === 0 && accountsError === null && (
        <div className="mt-4 rounded-lg border border-dashed border-border px-4 py-3 text-sm text-muted">
          <p>Connect a social account in Admin &gt; Social to cross-post this post.</p>
          <a
            href="/admin?tab=social"
            className="mt-2 inline-flex items-center gap-1.5 text-accent hover:underline"
          >
            Connect social account
          </a>
        </div>
      )}
      {showDialog && (
        <CrossPostDialog
          open={showDialog}
          onClose={handleDialogClose}
          accounts={accounts}
          postPath={filePath}
          postTitle={post.title}
          postExcerpt=""
          postLabels={post.labels}
        />
      )}
    </section>
  )
}
