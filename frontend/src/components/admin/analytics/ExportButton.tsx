import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import { fetchCreateExport, fetchExportStatus, fetchExportDownload } from '@/api/analytics'
import { HTTPError } from '@/api/client'

const MAX_POLLS = 30
const POLL_INTERVAL_MS = 2000

interface ExportButtonProps {
  disabled: boolean
}

export default function ExportButton({ disabled }: ExportButtonProps) {
  const [exporting, setExporting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleExport() {
    setExporting(true)
    setError(null)

    try {
      const { id } = await fetchCreateExport()

      // Poll for completion
      let done = false
      for (let i = 0; i < MAX_POLLS; i++) {
        // Wait before polling (skip wait on first check)
        if (i > 0) {
          await new Promise<void>((resolve) => { setTimeout(resolve, POLL_INTERVAL_MS) })
        }

        const status = await fetchExportStatus(id)
        if (status.finished) {
          done = true
          break
        }
      }

      if (!done) {
        setError('Export timed out. Please try again.')
        return
      }

      // Download
      const blob = await fetchExportDownload(id)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `analytics-export-${id}.csv`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (err) {
      if (err instanceof HTTPError && err.response.status === 401) {
        setError('Session expired. Please log in again.')
      } else {
        setError('Export failed. Please try again.')
      }
    } finally {
      setExporting(false)
    }
  }

  return (
    <div>
      <button
        onClick={() => { void handleExport() }}
        disabled={disabled || exporting}
        className="flex items-center gap-2 px-3 py-1.5 text-sm font-medium rounded-lg border border-border text-muted hover:text-ink hover:bg-surface transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {exporting ? (
          <>
            <Loader2 size={14} className="animate-spin" aria-hidden="true" />
            Exporting...
          </>
        ) : (
          'Export CSV'
        )}
      </button>
      {error !== null && (
        <p className="mt-1 text-sm text-red-600 dark:text-red-400">{error}</p>
      )}
    </div>
  )
}
