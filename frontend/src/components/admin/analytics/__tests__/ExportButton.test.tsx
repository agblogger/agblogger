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
import { HTTPError } from 'ky'

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

  it('downloads CSV on successful export', async () => {
    const blob = new Blob(['col1,col2\n1,2'], { type: 'text/csv' })
    mockFetchCreateExport.mockResolvedValue({ id: 42 })
    mockFetchExportStatus.mockResolvedValue({ id: 42, finished: true })
    mockFetchExportDownload.mockResolvedValue(blob)

    const createObjectURL = vi.fn().mockReturnValue('blob:test')
    const revokeObjectURL = vi.fn()
    globalThis.URL.createObjectURL = createObjectURL
    globalThis.URL.revokeObjectURL = revokeObjectURL

    const user = userEvent.setup()
    // Render before setting up appendchild spy so React can mount the component
    render(<ExportButton disabled={false} />)

    // Spy after render so React's initial mount is not intercepted
    const appendChildSpy = vi.spyOn(document.body, 'appendChild').mockImplementation((el) => el)

    await user.click(screen.getByRole('button', { name: 'Export CSV' }))

    await waitFor(() => {
      expect(mockFetchExportDownload).toHaveBeenCalledWith(42)
    })
    expect(createObjectURL).toHaveBeenCalledWith(blob)
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:test')

    appendChildSpy.mockRestore()
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

  it('shows session expired message on 401 error', async () => {
    // Construct an HTTPError with the required Response, Request, and options arguments.
    // The options argument uses an unknown cast to satisfy ky's NormalizedOptions shape.
    const httpError = new HTTPError(
      new Response(null, { status: 401, statusText: 'Unauthorized' }),
      new Request('http://localhost/api/admin/analytics/export'),
      {} as unknown as ConstructorParameters<typeof HTTPError>[2],
    )
    mockFetchCreateExport.mockRejectedValue(httpError)

    const user = userEvent.setup()
    render(<ExportButton disabled={false} />)
    await user.click(screen.getByRole('button', { name: 'Export CSV' }))

    await waitFor(() => {
      expect(screen.getByText('Session expired. Please log in again.')).toBeInTheDocument()
    })
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
