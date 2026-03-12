import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

const mockLogin = vi.fn()
let mockError: string | null = null
let mockIsLoading = false
let mockUser: { id: number; username: string } | null = null

const mockNavigate = vi.fn()

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  }
})

vi.mock('@/stores/authStore', () => ({
  useAuthStore: (selector: (s: {
    login: typeof mockLogin
    error: string | null
    isLoading: boolean
    user: typeof mockUser
  }) => unknown) =>
    selector({ login: mockLogin, error: mockError, isLoading: mockIsLoading, user: mockUser }),
}))

import LoginPage from '../LoginPage'

function renderLogin() {
  return render(
    <MemoryRouter>
      <LoginPage />
    </MemoryRouter>,
  )
}

describe('LoginPage', () => {
  beforeEach(() => {
    mockLogin.mockReset()
    mockNavigate.mockReset()
    mockError = null
    mockIsLoading = false
    mockUser = null
  })

  it('redirects to home when already authenticated', () => {
    mockUser = { id: 1, username: 'admin' }
    renderLogin()
    expect(mockNavigate).toHaveBeenCalledWith('/', { replace: true })
  })

  it('renders sign in form', () => {
    renderLogin()
    expect(screen.getByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(screen.getByLabelText(/Username/)).toBeInTheDocument()
    expect(screen.getByLabelText(/Password/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeInTheDocument()
  })

  it('calls login with credentials', async () => {
    mockLogin.mockResolvedValue(undefined)
    renderLogin()

    await userEvent.type(screen.getByLabelText(/Username/), 'admin')
    await userEvent.type(screen.getByLabelText(/Password/), 'secret')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(mockLogin).toHaveBeenCalledWith('admin', 'secret')
  })

  it('displays error from store', () => {
    mockError = 'Invalid credentials'
    renderLogin()
    expect(screen.getByText('Invalid credentials')).toBeInTheDocument()
  })

  it('shows loading state', () => {
    mockIsLoading = true
    renderLogin()
    const button = screen.getByRole('button', { name: 'Signing in...' })
    expect(button).toBeDisabled()
  })

  it('clears error when user types', async () => {
    mockError = 'Invalid credentials'
    renderLogin()
    expect(screen.getByText('Invalid credentials')).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText(/Username/), 'a')

    expect(screen.queryByText('Invalid credentials')).not.toBeInTheDocument()
  })

  it('shows required indicators on username and password', () => {
    renderLogin()
    const usernameLabel = screen.getByText((content, element) => {
      return element?.tagName === 'LABEL' && content.includes('Username') && content.includes('*')
    })
    const passwordLabel = screen.getByText((content, element) => {
      return element?.tagName === 'LABEL' && content.includes('Password') && content.includes('*')
    })
    expect(usernameLabel).toBeInTheDocument()
    expect(passwordLabel).toBeInTheDocument()
  })

  it('submits login form when pressing Enter in password field', async () => {
    mockLogin.mockResolvedValue(undefined)
    renderLogin()

    await userEvent.type(screen.getByLabelText(/Username/), 'admin')
    await userEvent.type(screen.getByLabelText(/Password/), 'secret{Enter}')

    expect(mockLogin).toHaveBeenCalledWith('admin', 'secret')
  })
})
