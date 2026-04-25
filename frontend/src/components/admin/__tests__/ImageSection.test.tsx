import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

const mockUploadAdminImage = vi.fn()
const mockRemoveAdminImage = vi.fn()

vi.mock('@/api/admin', () => ({
  uploadAdminImage: (...args: unknown[]) => mockUploadAdminImage(...args) as unknown,
  removeAdminImage: (...args: unknown[]) => mockRemoveAdminImage(...args) as unknown,
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

import ImageSection from '../ImageSection'

const baseSettings = {
  title: 'My Blog',
  description: '',
  timezone: 'UTC',
  password_change_disabled: false,
  favicon: null,
  image: null,
}

describe('ImageSection', () => {
  const onSavedSettings = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows upload button and "Website image" heading when no image is set', () => {
    render(
      <ImageSection
        initialImage={null}
        busy={false}
        onSavedSettings={onSavedSettings}
      />
    )
    expect(screen.getByText(/website image/i)).toBeInTheDocument()
    expect(screen.getByText(/upload image/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /remove/i })).not.toBeInTheDocument()
  })

  it('shows preview, replace, and remove when image is set', () => {
    render(
      <ImageSection
        initialImage="assets/image.png"
        busy={false}
        onSavedSettings={onSavedSettings}
      />
    )
    expect(screen.queryByText(/upload image \(/i)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /remove/i })).toBeInTheDocument()
    expect(screen.getByText(/replace/i)).toBeInTheDocument()
    expect(screen.getByText(/image\.png/)).toBeInTheDocument()
  })

  it('calls removeAdminImage and onSavedSettings on remove', async () => {
    const updatedSettings = { ...baseSettings, image: null }
    mockRemoveAdminImage.mockResolvedValue(updatedSettings)

    render(
      <ImageSection
        initialImage="assets/image.png"
        busy={false}
        onSavedSettings={onSavedSettings}
      />
    )

    await userEvent.click(screen.getByRole('button', { name: /remove/i }))

    await waitFor(() => {
      expect(mockRemoveAdminImage).toHaveBeenCalledOnce()
      expect(onSavedSettings).toHaveBeenCalledWith(updatedSettings)
    })
  })

  it('disables controls while busy', () => {
    render(
      <ImageSection
        initialImage="assets/image.png"
        busy={true}
        onSavedSettings={onSavedSettings}
      />
    )
    expect(screen.getByRole('button', { name: /remove/i })).toBeDisabled()
  })

  it('disables file upload input while busy when no image is set', () => {
    render(
      <ImageSection
        initialImage={null}
        busy={true}
        onSavedSettings={onSavedSettings}
      />
    )
    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    expect(input).toBeDisabled()
  })

  it('disables replace input while busy when an image is set', () => {
    render(
      <ImageSection
        initialImage="assets/image.png"
        busy={true}
        onSavedSettings={onSavedSettings}
      />
    )
    const inputs = document.querySelectorAll<HTMLInputElement>('input[type="file"]')
    inputs.forEach((input) => expect(input).toBeDisabled())
  })

  it('shows error message on remove failure', async () => {
    mockRemoveAdminImage.mockRejectedValue(new Error('Server error'))

    render(
      <ImageSection
        initialImage="assets/image.png"
        busy={false}
        onSavedSettings={onSavedSettings}
      />
    )

    await userEvent.click(screen.getByRole('button', { name: /remove/i }))

    await waitFor(() => {
      expect(screen.getByText(/failed to remove/i)).toBeInTheDocument()
    })
  })

  it('calls uploadAdminImage and onSavedSettings on file selection', async () => {
    const updatedSettings = { ...baseSettings, image: 'assets/image.png' }
    mockUploadAdminImage.mockResolvedValue(updatedSettings)

    render(
      <ImageSection
        initialImage={null}
        busy={false}
        onSavedSettings={onSavedSettings}
      />
    )

    const file = new File(['png'], 'image.png', { type: 'image/png' })
    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    await userEvent.upload(input, file)

    await waitFor(() => {
      expect(mockUploadAdminImage).toHaveBeenCalledWith(file)
      expect(onSavedSettings).toHaveBeenCalledWith(updatedSettings)
    })
  })

  it('shows file too large error on 413 upload response', async () => {
    const { MockHTTPError } = await import('@/test/MockHTTPError')
    mockUploadAdminImage.mockRejectedValue(new MockHTTPError(413))

    render(
      <ImageSection
        initialImage={null}
        busy={false}
        onSavedSettings={onSavedSettings}
      />
    )

    const file = new File(['png'], 'image.png', { type: 'image/png' })
    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    await userEvent.upload(input, file)

    await waitFor(() => {
      expect(screen.getByText(/file too large/i)).toBeInTheDocument()
    })
  })

  it('shows unsupported file type error on 422 upload response', async () => {
    const { MockHTTPError } = await import('@/test/MockHTTPError')
    mockUploadAdminImage.mockRejectedValue(new MockHTTPError(422))

    render(
      <ImageSection
        initialImage={null}
        busy={false}
        onSavedSettings={onSavedSettings}
      />
    )

    const file = new File(['png'], 'image.png', { type: 'image/png' })
    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    await userEvent.upload(input, file)

    await waitFor(() => {
      expect(screen.getByText(/unsupported file type/i)).toBeInTheDocument()
    })
  })

  it('refreshes preview URL after replacing image with same extension', async () => {
    const updatedSettings = { ...baseSettings, image: 'assets/image.png' }
    mockUploadAdminImage.mockResolvedValue(updatedSettings)

    render(
      <ImageSection
        initialImage="assets/image.png"
        busy={false}
        onSavedSettings={onSavedSettings}
      />
    )

    const initialSrc = screen.getByAltText<HTMLImageElement>('Current website image').src

    const file = new File(['new-png-bytes'], 'image.png', { type: 'image/png' })
    const replaceInput = document.querySelector('input[type="file"]') as HTMLInputElement
    await userEvent.upload(replaceInput, file)

    await waitFor(() => {
      expect(mockUploadAdminImage).toHaveBeenCalledWith(file)
    })

    const newSrc = screen.getByAltText<HTMLImageElement>('Current website image').src
    expect(newSrc).not.toBe(initialSrc)
  })
})
