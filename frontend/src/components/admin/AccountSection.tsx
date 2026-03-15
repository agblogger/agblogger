import { useEffect, useState } from 'react'
import { Lock, Save, User } from 'lucide-react'

import AlertBanner from '@/components/AlertBanner'
import { HTTPError } from '@/api/client'
import { parseErrorDetail } from '@/api/parseError'
import { changeAdminPassword } from '@/api/admin'
import { updateProfile } from '@/api/auth'
import { useAuthStore } from '@/stores/authStore'

const MIN_PASSWORD_LENGTH = 8

const INPUT_CLASSES =
  'w-full px-3 py-2 bg-paper-warm border border-border rounded-lg text-ink text-sm focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/20 disabled:opacity-50'

interface AccountSectionProps {
  busy: boolean
  onSaving: (saving: boolean) => void
  onDirtyChange: (dirty: boolean) => void
}

export default function AccountSection({ busy, onSaving, onDirtyChange }: AccountSectionProps) {
  const user = useAuthStore((s) => s.user)
  const setUser = useAuthStore((s) => s.setUser)

  // === Profile state ===
  const [username, setUsername] = useState(user?.username ?? '')
  const [displayName, setDisplayName] = useState(user?.display_name ?? '')
  const [profileError, setProfileError] = useState<string | null>(null)
  const [profileSuccess, setProfileSuccess] = useState<string | null>(null)
  const [savingProfile, setSavingProfile] = useState(false)

  // === Password state ===
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [passwordError, setPasswordError] = useState<string | null>(null)
  const [passwordSuccess, setPasswordSuccess] = useState<string | null>(null)
  const [savingPassword, setSavingPassword] = useState(false)

  const saving = savingProfile || savingPassword
  useEffect(() => { onSaving(saving) }, [saving, onSaving])

  const profileChanged =
    username !== (user?.username ?? '') ||
    displayName !== (user?.display_name ?? '')

  const passwordDirty =
    currentPassword.length > 0 || newPassword.length > 0 || confirmPassword.length > 0
  const isDirty = profileChanged || passwordDirty

  useEffect(() => { onDirtyChange(isDirty) }, [isDirty, onDirtyChange])
  useEffect(() => { return () => { onDirtyChange(false) } }, [onDirtyChange])

  async function handleSaveProfile() {
    setProfileError(null)
    setProfileSuccess(null)
    if (username.trim().length === 0) {
      setProfileError('Username is required.')
      return
    }
    setSavingProfile(true)
    try {
      const data: { username?: string; display_name?: string } = {}
      if (username !== user?.username) {
        data.username = username
      }
      if (displayName !== (user?.display_name ?? '')) {
        data.display_name = displayName
      }
      const updated = await updateProfile(data)
      setUser(updated)
      setProfileSuccess('Profile updated successfully.')
    } catch (err) {
      if (err instanceof HTTPError) {
        if (err.response.status === 409) {
          setProfileError('Username is already taken.')
        } else if (err.response.status === 422) {
          const detail = await parseErrorDetail(err.response, 'Invalid input.')
          setProfileError(detail)
        } else if (err.response.status === 401) {
          setProfileError('Session expired. Please log in again.')
        } else {
          setProfileError('Failed to update profile. Please try again.')
        }
      } else {
        setProfileError('Failed to update profile. The server may be unavailable.')
      }
    } finally {
      setSavingProfile(false)
    }
  }

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
    if (newPassword.length < MIN_PASSWORD_LENGTH) {
      setPasswordError(`New password must be at least ${MIN_PASSWORD_LENGTH} characters.`)
      return
    }
    setSavingPassword(true)
    try {
      const result = await changeAdminPassword({
        current_password: currentPassword,
        new_password: newPassword,
        confirm_password: confirmPassword,
      })
      setPasswordSuccess('Password changed successfully.')
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
      if (result.sessions_revoked === true) {
        onDirtyChange(false)
        void useAuthStore.getState().logout()
      }
    } catch (err) {
      if (err instanceof HTTPError) {
        if (err.response.status === 400 || err.response.status === 422) {
          const detail = await parseErrorDetail(err.response, 'Invalid request.')
          setPasswordError(detail)
        } else if (err.response.status === 429) {
          setPasswordError('Too many attempts. Please try again later.')
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
    <>
      {/* Profile section */}
      <section className="mb-8 p-5 bg-paper border border-border rounded-lg">
        <div className="flex items-center gap-2 mb-4">
          <User size={16} className="text-accent" />
          <h2 className="text-sm font-medium text-ink">Profile</h2>
        </div>

        {profileError !== null && (
          <AlertBanner variant="error" className="mb-4">{profileError}</AlertBanner>
        )}
        {profileSuccess !== null && (
          <AlertBanner variant="success" className="mb-4">{profileSuccess}</AlertBanner>
        )}

        <form
          onSubmit={(e) => {
            e.preventDefault()
            void handleSaveProfile()
          }}
          className="space-y-4 max-w-md"
        >
          <div>
            <label htmlFor="profile-username" className="block text-xs font-medium text-muted mb-1">
              Username
            </label>
            <input
              id="profile-username"
              type="text"
              value={username}
              onChange={(e) => {
                setUsername(e.target.value)
                setProfileError(null)
                setProfileSuccess(null)
              }}
              disabled={busy}
              className={INPUT_CLASSES}
            />
            <p className="text-xs text-muted mt-1">
              Must start with a letter or digit. Letters, digits, dots, hyphens, or underscores. 3-50 characters.
            </p>
          </div>

          <div>
            <label htmlFor="profile-display-name" className="block text-xs font-medium text-muted mb-1">
              Display Name
            </label>
            <input
              id="profile-display-name"
              type="text"
              value={displayName}
              onChange={(e) => {
                setDisplayName(e.target.value)
                setProfileError(null)
                setProfileSuccess(null)
              }}
              disabled={busy}
              placeholder="Shown as author on posts"
              className={`${INPUT_CLASSES} placeholder:text-muted/50`}
            />
          </div>

          <div className="mt-4">
            <button
              type="submit"
              disabled={busy || !profileChanged}
              className="flex items-center gap-1.5 px-5 py-2 text-sm font-medium bg-accent text-white rounded-lg
                       hover:bg-accent-light disabled:opacity-50 transition-colors"
            >
              <Save size={14} />
              {savingProfile ? 'Saving...' : 'Save Profile'}
            </button>
          </div>
        </form>
      </section>

      {/* Password section */}
      <section className="mb-8 p-5 bg-paper border border-border rounded-lg">
        <div className="flex items-center gap-2 mb-4">
          <Lock size={16} className="text-accent" />
          <h2 className="text-sm font-medium text-ink">Change Password</h2>
        </div>

        {passwordError !== null && (
          <AlertBanner variant="error" className="mb-4">{passwordError}</AlertBanner>
        )}
        {passwordSuccess !== null && (
          <AlertBanner variant="success" className="mb-4">{passwordSuccess}</AlertBanner>
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
              className={INPUT_CLASSES}
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
              className={INPUT_CLASSES}
            />
            <p className="text-xs text-muted mt-1">At least {MIN_PASSWORD_LENGTH} characters.</p>
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
              className={INPUT_CLASSES}
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
    </>
  )
}
