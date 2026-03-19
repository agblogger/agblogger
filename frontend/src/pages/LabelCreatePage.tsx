import { useEffect, useState } from 'react'
import AlertBanner from '@/components/AlertBanner'
import LoadingSpinner from '@/components/LoadingSpinner'
import BackLink from '@/components/BackLink'
import ErrorBlock from '@/components/ErrorBlock'
import { useNavigate } from 'react-router-dom'
import { Tag } from 'lucide-react'

import { useUnsavedChanges } from '@/hooks/useUnsavedChanges'
import { useAuthStore } from '@/stores/authStore'
import { createLabel, fetchLabels } from '@/api/labels'
import { HTTPError } from '@/api/client'
import type { LabelResponse } from '@/api/client'
import LabelNamesEditor from '@/components/labels/LabelNamesEditor'
import LabelParentsSelector from '@/components/labels/LabelParentsSelector'

const LABEL_ID_REGEX = /^[a-z0-9][a-z0-9-]*$/

export default function LabelCreatePage() {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const isInitialized = useAuthStore((s) => s.isInitialized)

  const [allLabels, setAllLabels] = useState<LabelResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Form state
  const [labelId, setLabelId] = useState('')
  const [names, setNames] = useState<string[]>([])
  const [parents, setParents] = useState<string[]>([])
  const [creating, setCreating] = useState(false)

  const isValidId = labelId.length > 0 && labelId.length <= 100 && LABEL_ID_REGEX.test(labelId)

  const isDirty = labelId.length > 0 || names.length > 0 || parents.length > 0

  const { markSaved } = useUnsavedChanges(isDirty)

  useEffect(() => {
    if (isInitialized && !user) {
      void navigate('/login', { replace: true })
    }
  }, [user, isInitialized, navigate])

  useEffect(() => {
    if (!user) return
    fetchLabels()
      .then(setAllLabels)
      .catch((err: unknown) => {
        if (err instanceof HTTPError && err.response.status === 401) {
          setError('Session expired. Please log in again.')
        } else {
          console.error('Failed to load labels:', err)
          setError('Failed to load labels. Please try again later.')
        }
      })
      .finally(() => setLoading(false))
  }, [user])

  async function handleCreate() {
    if (!isValidId) return
    setCreating(true)
    setError(null)
    try {
      await createLabel({ id: labelId, names, parents })
      markSaved()
      void navigate(`/labels/${labelId}`)
    } catch (err) {
      if (err instanceof HTTPError) {
        const status = err.response.status
        switch (status) {
          case 409:
            setError('A label with this ID already exists.')
            break
          case 422:
            setError('Invalid label ID. Use lowercase letters, numbers, and hyphens.')
            break
          case 404:
            setError('One or more selected parent labels no longer exist.')
            break
          case 401:
            setError('Session expired. Please log in again.')
            break
          default:
            console.error(`Failed to create label: unexpected HTTP ${status}`)
            setError('Failed to create label. Please try again.')
        }
      } else {
        console.error('Failed to create label:', err)
        setError('Failed to create label. Please try again.')
      }
    } finally {
      setCreating(false)
    }
  }

  if (!isInitialized || !user) {
    return null
  }

  if (loading) {
    return <LoadingSpinner />
  }

  if (error !== null && allLabels.length === 0) {
    return <ErrorBlock message={error} backTo="/labels" backLabel="Back to labels" />
  }

  return (
    <div className="animate-fade-in">
      <div className="mb-6">
        <BackLink to="/labels" label="Back to labels" />
      </div>

      <div className="flex items-center gap-3 mb-8">
        <Tag size={20} className="text-accent" />
        <h1 className="font-display text-3xl text-ink">New Label</h1>
        <button
          onClick={() => void handleCreate()}
          disabled={creating || !isValidId}
          className="ml-auto px-6 py-2.5 text-sm font-medium bg-accent text-white rounded-lg
                   hover:bg-accent-light disabled:opacity-50 transition-colors"
        >
          {creating ? 'Creating...' : 'Create Label'}
        </button>
      </div>

      {error !== null && (
        <AlertBanner variant="error" className="mb-6">{error}</AlertBanner>
      )}

      <section className="mb-8 p-5 bg-paper border border-border rounded-lg">
        <h2 className="text-sm font-medium text-ink mb-3">Label ID</h2>
        <input
          type="text"
          value={labelId}
          onChange={(e) => { setLabelId(e.target.value); setError(null) }}
          disabled={creating}
          maxLength={100}
          placeholder="e.g. machine-learning"
          aria-describedby="label-id-hint"
          className="w-full px-3 py-2 bg-paper-warm border border-border rounded-lg
                   text-ink text-sm
                   focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/20
                   disabled:opacity-50"
        />
        <p id="label-id-hint" className="text-xs text-muted mt-2">
          Lowercase letters, numbers, and hyphens. Cannot be changed after creation.
        </p>
      </section>

      <LabelNamesEditor
        names={names}
        onNamesChange={(updated) => { setNames(updated); setError(null) }}
        disabled={creating}
      />

      <LabelParentsSelector
        parents={parents}
        onParentsChange={(updated) => { setParents(updated); setError(null) }}
        availableParents={allLabels}
        disabled={creating}
      />
    </div>
  )
}
