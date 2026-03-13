import { useEffect, useState, useMemo } from 'react'
import LoadingSpinner from '@/components/LoadingSpinner'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { ArrowLeft, X, Settings, Trash2 } from 'lucide-react'

import { useAuthStore } from '@/stores/authStore'
import { fetchLabel, fetchLabels, updateLabel, deleteLabel } from '@/api/labels'
import { HTTPError } from '@/api/client'
import type { LabelResponse } from '@/api/client'
import { computeDescendants } from '@/components/labels/graphUtils'

export default function LabelSettingsPage() {
  const { labelId } = useParams()
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const isInitialized = useAuthStore((s) => s.isInitialized)

  const [label, setLabel] = useState<LabelResponse | null>(null)
  const [allLabels, setAllLabels] = useState<LabelResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Editable state
  const [names, setNames] = useState<string[]>([])
  const [parents, setParents] = useState<string[]>([])
  const [newName, setNewName] = useState('')

  // Async operation state
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const busy = saving || deleting

  useEffect(() => {
    if (isInitialized && !user) {
      void navigate('/login', { replace: true })
    }
  }, [user, isInitialized, navigate])

  useEffect(() => {
    if (labelId === undefined) return
    setLoading(true)
    setError(null)
    void Promise.all([fetchLabel(labelId), fetchLabels()])
      .then(([l, all]) => {
        setLabel(l)
        setAllLabels(all)
        setNames([...l.names])
        setParents([...l.parents])
      })
      .catch((err: unknown) => {
        if (err instanceof HTTPError && err.response.status === 404) {
          setError('Label not found.')
        } else if (err instanceof HTTPError && err.response.status === 401) {
          setError('Session expired. Please log in again.')
        } else {
          setError('Failed to load label data. Please try again later.')
        }
      })
      .finally(() => {
        setLoading(false)
      })
  }, [labelId])

  const excludedIds = useMemo(() => {
    if (labelId === undefined) return new Set<string>()
    const labelsById = new Map(allLabels.map((l) => [l.id, l]))
    const descendants = computeDescendants(labelId, labelsById)
    descendants.add(labelId)
    return descendants
  }, [labelId, allLabels])

  const availableParents = allLabels.filter((l) => !excludedIds.has(l.id))

  function handleRemoveName(index: number) {
    setNames(names.filter((_, i) => i !== index))
    setError(null)
  }

  function handleAddName() {
    const trimmed = newName.trim()
    if (!trimmed) return
    if (names.includes(trimmed)) return
    setNames([...names, trimmed])
    setNewName('')
    setError(null)
  }

  function handleToggleParent(parentId: string) {
    if (parents.includes(parentId)) {
      setParents(parents.filter((p) => p !== parentId))
    } else {
      setParents([...parents, parentId])
    }
    setError(null)
  }

  async function handleSave() {
    if (labelId === undefined) return
    setSaving(true)
    setError(null)
    try {
      const updated = await updateLabel(labelId, { names, parents })
      setLabel(updated)
      setNames([...updated.names])
      setParents([...updated.parents])
    } catch (err) {
      if (err instanceof HTTPError) {
        const status = err.response.status
        if (status === 409) {
          setError('Cannot save: adding these parents would create a cycle in the label hierarchy.')
        } else if (status === 404) {
          setError('One or more selected parent labels no longer exist.')
        } else if (status === 401) {
          setError('Session expired. Please log in again.')
        } else {
          setError('Failed to save label. Please try again.')
        }
      } else {
        setError('Failed to save label. The server may be unavailable.')
      }
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete() {
    if (labelId === undefined) return
    setDeleting(true)
    setError(null)
    try {
      await deleteLabel(labelId)
      void navigate('/labels', { replace: true })
    } catch (err) {
      if (err instanceof HTTPError && err.response.status === 401) {
        setError('Session expired. Please log in again.')
      } else {
        setError('Failed to delete label. Please try again.')
      }
      setShowDeleteConfirm(false)
    } finally {
      setDeleting(false)
    }
  }

  if (!isInitialized || !user) {
    return null
  }

  if (loading) {
    return <LoadingSpinner />
  }

  if (error !== null && label === null) {
    return (
      <div className="text-center py-24">
        <p className="text-red-600 dark:text-red-400">{error}</p>
        <Link to="/labels" className="text-accent text-sm hover:underline mt-4 inline-block">
          Back to labels
        </Link>
      </div>
    )
  }

  return (
    <div className="animate-fade-in">
      <Link
        to={`/labels/${labelId}`}
        className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink transition-colors mb-6"
      >
        <ArrowLeft size={14} />
        Back to #{labelId}
      </Link>

      <div className="flex items-center gap-3 mb-8">
        <Settings size={20} className="text-accent" />
        <h1 className="font-display text-3xl text-ink">Label Settings: #{labelId}</h1>
      </div>

      {error !== null && (
        <div className="mb-6 text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800/40 rounded-lg px-4 py-3">
          {error}
        </div>
      )}

      {/* Names section */}
      <section className="mb-8 p-5 bg-paper border border-border rounded-lg">
        <h2 className="text-sm font-medium text-ink mb-3">Display Names</h2>
        <div className="flex flex-wrap gap-2 mb-3">
          {names.map((name, i) => (
            <span
              key={i}
              className="inline-flex items-center gap-1 px-3 py-1.5 text-sm
                       bg-tag-bg text-tag-text rounded-full"
            >
              {name}
              <button
                onClick={() => handleRemoveName(i)}
                disabled={busy}
                className="ml-0.5 p-0.5 rounded-full hover:bg-black/10 disabled:opacity-30
                         transition-colors"
                aria-label={`Remove name "${name}"`}
              >
                <X size={12} />
              </button>
            </span>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                handleAddName()
              }
            }}
            disabled={busy}
            placeholder="Add a display name..."
            className="flex-1 px-3 py-2 bg-paper-warm border border-border rounded-lg
                     text-ink text-sm
                     focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/20
                     disabled:opacity-50"
          />
          <button
            onClick={handleAddName}
            disabled={busy || newName.trim().length === 0}
            className="px-4 py-2 text-sm font-medium border border-border rounded-lg
                     hover:bg-paper-warm disabled:opacity-50 transition-colors"
          >
            Add
          </button>
        </div>
        <p className="text-xs text-muted mt-2">Optional aliases shown alongside the label ID.</p>
      </section>

      {/* Parents section */}
      <section className="mb-8 p-5 bg-paper border border-border rounded-lg">
        <h2 className="text-sm font-medium text-ink mb-3">Parent Labels</h2>
        {availableParents.length === 0 ? (
          <p className="text-sm text-muted">No other labels available as parents.</p>
        ) : (
          <div className="space-y-2 max-h-64 overflow-y-auto">
            {availableParents.map((candidate) => (
              <label
                key={candidate.id}
                className="flex items-center gap-2.5 px-3 py-2 rounded-lg hover:bg-paper-warm
                         cursor-pointer transition-colors"
              >
                <input
                  type="checkbox"
                  checked={parents.includes(candidate.id)}
                  onChange={() => handleToggleParent(candidate.id)}
                  disabled={busy}
                  className="rounded border-border text-accent focus:ring-accent/20"
                />
                <span className="text-sm text-ink">#{candidate.id}</span>
                {candidate.names.length > 0 && (
                  <span className="text-xs text-muted">({candidate.names.join(', ')})</span>
                )}
              </label>
            ))}
          </div>
        )}
        <p className="text-xs text-muted mt-2">
          Labels that are descendants of #{labelId} are excluded to prevent cycles.
        </p>
      </section>

      {/* Save button */}
      <div className="mb-10">
        <button
          onClick={() => void handleSave()}
          disabled={busy}
          className="px-6 py-2.5 text-sm font-medium bg-accent text-white rounded-lg
                   hover:bg-accent-light disabled:opacity-50 transition-colors"
        >
          {saving ? 'Saving...' : 'Save Changes'}
        </button>
      </div>

      {/* Delete section */}
      <section className="p-5 border border-red-200 dark:border-red-800/40 rounded-lg">
        <h2 className="text-sm font-medium text-red-700 dark:text-red-400 mb-2">Danger Zone</h2>
        <p className="text-sm text-muted mb-4">
          Deleting this label will remove it from all posts and from the label hierarchy. This
          action cannot be undone.
        </p>
        {showDeleteConfirm ? (
          <div className="flex items-center gap-3">
            <button
              onClick={() => void handleDelete()}
              disabled={busy}
              className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium
                       bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50
                       transition-colors"
            >
              <Trash2 size={14} />
              {deleting ? 'Deleting...' : 'Confirm Delete'}
            </button>
            <button
              onClick={() => setShowDeleteConfirm(false)}
              disabled={busy}
              className="px-4 py-2 text-sm font-medium border border-border rounded-lg
                       hover:bg-paper-warm disabled:opacity-50 transition-colors"
            >
              Cancel
            </button>
          </div>
        ) : (
          <button
            onClick={() => setShowDeleteConfirm(true)}
            disabled={busy}
            className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium
                     text-red-600 dark:text-red-400 border border-red-300 dark:border-red-700 rounded-lg hover:bg-red-50 dark:hover:bg-red-950/30
                     disabled:opacity-50 transition-colors"
          >
            <Trash2 size={14} />
            Delete Label
          </button>
        )}
      </section>
    </div>
  )
}
