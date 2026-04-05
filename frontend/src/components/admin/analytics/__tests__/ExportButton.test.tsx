import { render, screen, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

const mockFetchCreateExport = vi.fn()
const mockFetchExportStatus = vi.fn()
const mockFetchExportDownload = vi.fn()

vi.mock('@/api/analytics', () => ({
  fetchCreateExport: (...args: unknown[]) => mockFetchCreateExport(...args) as unknown,
  fetchExportStatus: (...args: unknown[]) => mockFetchExportStatus(...args) as unknown,
  fetchExportDownload: (...args: unknown[]) => mockFetchExportDownload(...args) as unknown,
}))

import ExportButton from '../ExportButton'

describe('ExportButton', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders "Export CSV" button', () => {
    render(<ExportButton disabled={false} />)
    expect(screen.getByRole('button', { name: 'Export CSV' })).toBeInTheDocument()
  })

  it('disables button when disabled=true', () => {
    render(<ExportButton disabled={true} />)
    expect(screen.getByRole('button', { name: 'Export CSV' })).toBeDisabled()
  })

  it('shows "Exporting..." state while export is in progress', async () => {
    // Use a pending promise so we stay in exporting state
    let reject!: (err: Error) => void
    const pending = new Promise<never>((_, rej) => { reject = rej })
    mockFetchCreateExport.mockReturnValue(pending)

    const user = userEvent.setup()
    render(<ExportButton disabled={false} />)

    // Start the export (don't await — it's in progress)
    const clickPromise = user.click(screen.getByRole('button', { name: 'Export CSV' }))

    await waitFor(() => {
      expect(screen.queryByText('Exporting...')).toBeInTheDocument()
    })
    expect(screen.getByRole('button')).toBeDisabled()

    // Clean up — reject the promise so the component settles
    reject(new Error('cleanup'))
    await clickPromise.catch(() => {})
  })

  it('shows error message when fetchCreateExport fails', async () => {
    mockFetchCreateExport.mockRejectedValue(new Error('Network error'))

    const user = userEvent.setup()
    render(<ExportButton disabled={false} />)

    await user.click(screen.getByRole('button', { name: 'Export CSV' }))

    await waitFor(() => {
      expect(screen.getByText('Export failed. Please try again.')).toBeInTheDocument()
    })
    // Button should be re-enabled after error
    expect(screen.getByRole('button', { name: 'Export CSV' })).not.toBeDisabled()
  })

  it('shows timeout error when export never finishes', async () => {
    mockFetchCreateExport.mockResolvedValue({ id: 1 })
    // Always return not finished
    mockFetchExportStatus.mockResolvedValue({ id: 1, finished: false })

    // Use fake timers for this test only — set them up before rendering
    vi.useFakeTimers()
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    render(<ExportButton disabled={false} />)

    // Click the button — don't await so we can drive timers
    void user.click(screen.getByRole('button', { name: 'Export CSV' }))

    // Drive through all 30 poll intervals (each waits 2000ms)
    for (let i = 0; i < 31; i++) {
      await act(async () => {
        await vi.runAllTimersAsync()
      })
    }

    vi.useRealTimers()

    expect(screen.getByText('Export timed out. Please try again.')).toBeInTheDocument()
  }, 10000)
})
