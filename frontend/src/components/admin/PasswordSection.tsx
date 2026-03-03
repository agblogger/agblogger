import { useEffect, useState } from 'react'
import { Lock } from 'lucide-react'

import { HTTPError } from '@/api/client'
import { parseErrorDetail } from '@/api/parseError'
import { changeAdminPassword } from '@/api/admin'

interface PasswordSectionProps {
  busy: boolean
  onSaving: (saving: boolean) => void
}

export default function PasswordSection({ busy, onSaving }: PasswordSectionProps) {
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [passwordError, setPasswordError] = useState<string | null>(null)
  const [passwordSuccess, setPasswordSuccess] = useState<string | null>(null)
  const [savingPassword, setSavingPassword] = useState(false)

  useEffect(() => { onSaving(savingPassword) }, [savingPassword, onSaving])

  async function handleChangePassword() {
    setPasswordError(null)
    setPasswordSuccess(null)
    if (
      currentPassword.length === 0 ||
      newPassword.length === 0 ||
      confirmPassword.length === 0
    ) {
      setPasswordError('All fields are required.')
      return
    }
    if (newPassword !== confirmPassword) {
      setPasswordError('New passwords do not match.')
      return
    }
    if (newPassword.length < 12) {
      setPasswordError('New password must be at least 12 characters.')
      return
    }
    setSavingPassword(true)
    try {
      await changeAdminPassword({
        current_password: currentPassword,
        new_password: newPassword,
        confirm_password: confirmPassword,
      })
      setPasswordSuccess('Password changed successfully.')
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
    } catch (err) {
      if (err instanceof HTTPError) {
        if (err.response.status === 400) {
          const detail = await parseErrorDetail(err.response, 'Invalid request.')
          setPasswordError(detail)
        } else if (err.response.status === 401) {
          setPasswordError('Session expired. Please log in again.')
        } else {
          setPasswordError('Failed to change password. Please try again.')
        }
      } else {
        setPasswordError('Failed to change password. The server may be unavailable.')
      }
    } finally {
      setSavingPassword(false)
    }
  }

  return (
    <section className="mb-8 p-5 bg-paper border border-border rounded-lg">
      <div className="flex items-center gap-2 mb-4">
        <Lock size={16} className="text-accent" />
        <h2 className="text-sm font-medium text-ink">Change Password</h2>
      </div>

      {passwordError !== null && (
        <div className="mb-4 text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800/40 rounded-lg px-4 py-3">
          {passwordError}
        </div>
      )}
      {passwordSuccess !== null && (
        <div className="mb-4 text-sm text-green-700 dark:text-green-400 bg-green-50 dark:bg-green-950/30 border border-green-200 dark:border-green-800/40 rounded-lg px-4 py-3">
          {passwordSuccess}
        </div>
      )}

      <form
        onSubmit={(e) => {
          e.preventDefault()
          void handleChangePassword()
        }}
        className="space-y-4 max-w-md"
      >
        <div>
          <label
            htmlFor="current-password"
            className="block text-xs font-medium text-muted mb-1"
          >
            Current Password *
          </label>
          <input
            id="current-password"
            name="current-password"
            type="password"
            autoComplete="current-password"
            value={currentPassword}
            onChange={(e) => {
              setCurrentPassword(e.target.value)
              setPasswordError(null)
              setPasswordSuccess(null)
            }}
            disabled={busy}
            className="w-full px-3 py-2 bg-paper-warm border border-border rounded-lg
                     text-ink text-sm
                     focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/20
                     disabled:opacity-50"
          />
        </div>

        <div>
          <label htmlFor="new-password" className="block text-xs font-medium text-muted mb-1">
            New Password *
          </label>
          <input
            id="new-password"
            name="new-password"
            type="password"
            autoComplete="new-password"
            value={newPassword}
            onChange={(e) => {
              setNewPassword(e.target.value)
              setPasswordError(null)
              setPasswordSuccess(null)
            }}
            disabled={busy}
            className="w-full px-3 py-2 bg-paper-warm border border-border rounded-lg
                     text-ink text-sm
                     focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/20
                     disabled:opacity-50"
          />
          <p className="text-xs text-muted mt-1">At least 12 characters.</p>
        </div>

        <div>
          <label
            htmlFor="confirm-password"
            className="block text-xs font-medium text-muted mb-1"
          >
            Confirm New Password *
          </label>
          <input
            id="confirm-password"
            name="confirm-password"
            type="password"
            autoComplete="new-password"
            value={confirmPassword}
            onChange={(e) => {
              setConfirmPassword(e.target.value)
              setPasswordError(null)
              setPasswordSuccess(null)
            }}
            disabled={busy}
            className="w-full px-3 py-2 bg-paper-warm border border-border rounded-lg
                     text-ink text-sm
                     focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/20
                     disabled:opacity-50"
          />
        </div>

        <div className="mt-4">
          <button
            type="submit"
            disabled={busy}
            className="flex items-center gap-1.5 px-5 py-2 text-sm font-medium bg-accent text-white rounded-lg
                     hover:bg-accent-light disabled:opacity-50 transition-colors"
          >
            <Lock size={14} />
            {savingPassword ? 'Changing...' : 'Change Password'}
          </button>
        </div>
      </form>
    </section>
  )
}
