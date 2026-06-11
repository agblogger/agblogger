import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import SubscribePage from '@/pages/SubscribePage'
import * as apiMod from '@/api/subscriptions'
import { useSiteStore } from '@/stores/siteStore'

vi.mock('@/api/client', async () => {
  const { MockHTTPError } = await import('@/test/MockHTTPError')
  return { default: {}, HTTPError: MockHTTPError }
})

vi.mock('@/api/subscriptions')

function renderPage() {
  return render(
    <MemoryRouter>
      <SubscribePage />
    </MemoryRouter>,
  )
}

describe('SubscribePage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useSiteStore.setState({
      config: {
        title: 'Blog',
        description: '',
        pages: [],
        subscriptions_enabled: true,
        subscription_compliance: {
          controller_name: 'Jane Controller',
          controller_contact: 'privacy@example.com',
          privacy_policy_url: 'https://example.com/legal/privacy',
        },
      },
      isLoading: false,
      error: null,
    })
  })

  it('submits the email and shows a confirmation message', async () => {
    vi.mocked(apiMod.subscribe).mockResolvedValue({ message: 'Please check your inbox to confirm your subscription.' })
    renderPage()
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'r@x.com' } })
    fireEvent.click(screen.getByRole('button', { name: /subscribe/i }))
    await waitFor(() => expect(apiMod.subscribe).toHaveBeenCalledWith('r@x.com'))
    expect(await screen.findByText(/check your inbox/i)).toBeInTheDocument()
  })

  it('omits controller sentence when compliance fields are absent', () => {
    useSiteStore.setState({
      config: {
        title: 'Blog',
        description: '',
        pages: [],
        subscriptions_enabled: true,
        subscription_compliance: {
          controller_name: null,
          controller_contact: null,
          privacy_policy_url: null,
        },
      },
      isLoading: false,
      error: null,
    })
    renderPage()
    expect(screen.getByRole('link', { name: /privacy policy/i })).toHaveAttribute(
      'href',
      '/page/privacy',
    )
  })

  it('disables the submit button and input while submitting', async () => {
    let resolveSubscribe!: (v: { message: string }) => void
    const promise = new Promise<{ message: string }>((res) => { resolveSubscribe = res })
    vi.mocked(apiMod.subscribe).mockReturnValue(promise)
    renderPage()

    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'r@x.com' } })
    fireEvent.click(screen.getByRole('button', { name: /subscribe/i }))

    // While in flight: button and input must be disabled
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /subscribing/i })).toBeDisabled()
    })
    expect(screen.getByLabelText(/email/i)).toBeDisabled()

    // Resolve the promise inside act so state updates are flushed cleanly
    await act(async () => {
      resolveSubscribe({ message: 'ok' })
      await promise
    })
  })

  it('shows a rate-limit message on 429', async () => {
    const { MockHTTPError } = await import('@/test/MockHTTPError')
    vi.mocked(apiMod.subscribe).mockRejectedValue(new MockHTTPError(429))
    renderPage()
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'r@x.com' } })
    fireEvent.click(screen.getByRole('button', { name: /subscribe/i }))
    expect(await screen.findByText(/too many requests/i)).toBeInTheDocument()
  })

  it('shows a generic error message on non-429 failures', async () => {
    vi.mocked(apiMod.subscribe).mockRejectedValue(new Error('network'))
    renderPage()
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'r@x.com' } })
    fireEvent.click(screen.getByRole('button', { name: /subscribe/i }))
    expect(await screen.findByText(/unavailable/i)).toBeInTheDocument()
  })
})
