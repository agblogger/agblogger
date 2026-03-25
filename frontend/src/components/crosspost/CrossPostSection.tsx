import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Share2 } from 'lucide-react'

import type { SocialAccount } from '@/api/crosspost'
import type { PostDetail } from '@/api/client'
import { extractErrorDetail } from '@/api/parseError'
import CrossPostDialog from '@/components/crosspost/CrossPostDialog'
import CrossPostHistory from '@/components/crosspost/CrossPostHistory'
import { useSocialAccounts } from '@/hooks/useSocialAccounts'
import { useCrossPostHistory } from '@/hooks/useCrossPostHistory'

interface CrossPostSectionProps {
  filePath: string
  post: PostDetail
}

export default function CrossPostSection({ filePath, post }: CrossPostSectionProps) {
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [accountsError, setAccountsError] = useState<string | null>(null)
  const [showDialog, setShowDialog] = useState(false)

  const {
    data: historyData,
    error: historyErr,
    isLoading: historyLoading,
    mutate: mutateHistory,
  } = useCrossPostHistory(post.is_draft ? null : filePath)

  const {
    data: accountsData = [],
    error: accountsErr,
    isLoading: accountsLoading,
  } = useSocialAccounts()

  const historyItems = historyData?.items ?? []
  const accounts: SocialAccount[] = accountsData

  useEffect(() => {
    if (historyErr === undefined || historyErr === null) {
      setHistoryError(null)
      return
    }
    void extractErrorDetail(
      historyErr,
      'Failed to load cross-post history. Please try again.',
    ).then(setHistoryError)
  }, [historyErr])

  useEffect(() => {
    if (accountsErr === undefined || accountsErr === null) {
      setAccountsError(null)
      return
    }
    void extractErrorDetail(
      accountsErr,
      'Failed to load connected social accounts. Please try again.',
    ).then(setAccountsError)
  }, [accountsErr])

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
    void mutateHistory()
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
      {[...new Set([historyError, accountsError].filter((msg): msg is string => msg !== null))].map((msg) => (
        <div key={msg} className="mb-4 text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800/40 rounded-lg px-4 py-3">
          {msg}
        </div>
      ))}
      <CrossPostHistory items={historyItems} loading={historyLoading} />
      {!accountsLoading && accounts.length === 0 && accountsError === null && (
        <div className="mt-4 rounded-lg border border-dashed border-border px-4 py-3 text-sm text-muted">
          <p>Connect a social account in Admin &gt; Social to cross-post this post.</p>
          <Link
            to="/admin?tab=social"
            className="mt-2 inline-flex items-center gap-1.5 text-accent hover:underline"
          >
            Connect social account
          </Link>
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
