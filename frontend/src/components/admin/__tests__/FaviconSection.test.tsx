import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

const mockUploadAdminFavicon = vi.fn()
const mockRemoveAdminFavicon = vi.fn()

vi.mock('@/api/admin', () => ({
  uploadAdminFavicon: (...args: unknown[]) => mockUploadAdminFavicon(...args) as unknown,
  removeAdminFavicon: (...args: unknown[]) => mockRemoveAdminFavicon(...args) as unknown,
}))

vi.mock('@/api/client', async () => {
  const { MockHTTPError } = await import('@/test/MockHTTPError')
  return {
    default: {},
    HTTPError: MockHTTPError,
  }
})

vi.mock('@/stores/siteStore', () => ({
  refreshSiteConfig: vi.fn(),
}))

import FaviconSection from '../FaviconSection'

const baseSettings = {
  title: 'My Blog',
  description: '',
  timezone: 'UTC',
  password_change_disabled: false,
  favicon: null,
}

describe('FaviconSection', () => {
  const onSavedSettings = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows upload button when no favicon is set', () => {
    render(
      <FaviconSection
        initialFavicon={null}
        busy={false}
        onSavedSettings={onSavedSettings}
      />
    )
    expect(screen.getByText(/upload image/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /remove/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /replace/i })).not.toBeInTheDocument()
  })

  it('shows preview, replace, and remove when favicon is set', () => {
    render(
      <FaviconSection
        initialFavicon="assets/favicon.png"
        busy={false}
        onSavedSettings={onSavedSettings}
      />
    )
    expect(screen.queryByText(/upload image/i)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /remove/i })).toBeInTheDocument()
    expect(screen.getByText(/replace/i)).toBeInTheDocument()
    expect(screen.getByText(/favicon\.png/)).toBeInTheDocument()
  })

  it('calls removeAdminFavicon and onSavedSettings on remove', async () => {
    const updatedSettings = { ...baseSettings, favicon: null }
    mockRemoveAdminFavicon.mockResolvedValue(updatedSettings)

    render(
      <FaviconSection
        initialFavicon="assets/favicon.png"
        busy={false}
        onSavedSettings={onSavedSettings}
      />
    )

    await userEvent.click(screen.getByRole('button', { name: /remove/i }))

    await waitFor(() => {
      expect(mockRemoveAdminFavicon).toHaveBeenCalledOnce()
      expect(onSavedSettings).toHaveBeenCalledWith(updatedSettings)
    })
  })

  it('disables controls while busy', () => {
    render(
      <FaviconSection
        initialFavicon="assets/favicon.png"
        busy={true}
        onSavedSettings={onSavedSettings}
      />
    )
    expect(screen.getByRole('button', { name: /remove/i })).toBeDisabled()
  })

  it('shows error message on remove failure', async () => {
    mockRemoveAdminFavicon.mockRejectedValue(new Error('Server error'))

    render(
      <FaviconSection
        initialFavicon="assets/favicon.png"
        busy={false}
        onSavedSettings={onSavedSettings}
      />
    )

    await userEvent.click(screen.getByRole('button', { name: /remove/i }))

    await waitFor(() => {
      expect(screen.getByText(/failed to remove/i)).toBeInTheDocument()
    })
  })
})
