import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/stores/authStore'

export default function LoginPage() {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const loginAction = useAuthStore((s) => s.login)
  const storeError = useAuthStore((s) => s.error)
  const isLoading = useAuthStore((s) => s.isLoading)

  const [localError, setLocalError] = useState<string | null>(null)

  useEffect(() => {
    if (user) {
      void navigate('/', { replace: true })
    }
  }, [user, navigate])

  useEffect(() => {
    setLocalError(storeError)
  }, [storeError])

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    try {
      await loginAction(username, password)
      void navigate('/')
    } catch {
      // Error is set in store
    }
  }

  return (
    <div className="max-w-sm mx-auto pt-16 animate-fade-in">
      <h1 className="font-display text-3xl text-center mb-8">Sign in</h1>

      <form onSubmit={(e) => void handleSubmit(e)} className="space-y-4">
        {localError !== null && (
          <div className="text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800/40 rounded-lg px-4 py-3">
            {localError}
          </div>
        )}

        <div>
          <label htmlFor="username" className="block text-sm font-medium text-ink mb-1.5">
            Username *
          </label>
          <input
            id="username"
            name="username"
            type="text"
            autoComplete="username"
            value={username}
            onChange={(e) => {
              setUsername(e.target.value)
              setLocalError(null)
            }}
            required
            className="w-full px-4 py-2.5 bg-paper-warm border border-border rounded-lg
                     text-ink focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/20
                     transition-colors"
          />
        </div>

        <div>
          <label htmlFor="password" className="block text-sm font-medium text-ink mb-1.5">
            Password *
          </label>
          <input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => {
              setPassword(e.target.value)
              setLocalError(null)
            }}
            required
            className="w-full px-4 py-2.5 bg-paper-warm border border-border rounded-lg
                     text-ink focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/20
                     transition-colors"
          />
        </div>

        <button
          type="submit"
          disabled={isLoading}
          className="w-full py-2.5 bg-accent text-white rounded-lg font-medium
                   hover:bg-accent-light disabled:opacity-50 transition-colors"
        >
          {isLoading ? 'Signing in...' : 'Sign in'}
        </button>
      </form>
    </div>
  )
}
