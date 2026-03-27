import { useCallback, useEffect, useState, useMemo } from 'react'
import AlertBanner from '@/components/AlertBanner'
import LoadingSpinner from '@/components/LoadingSpinner'
import BackLink from '@/components/BackLink'
import ErrorBlock from '@/components/ErrorBlock'
import { useParams, useNavigate } from 'react-router-dom'
import { Settings, Trash2 } from 'lucide-react'

import { useUnsavedChanges } from '@/hooks/useUnsavedChanges'
import { useRequireAdmin } from '@/hooks/useRequireAdmin'
import { fetchLabel, updateLabel, deleteLabel } from '@/api/labels'
import { HTTPError } from '@/api/client'
import type { LabelResponse } from '@/api/client'
import { useLabels } from '@/hooks/useLabels'
import { computeDescendants } from '@/components/labels/graphUtils'
import LabelNamesEditor from '@/components/labels/LabelNamesEditor'
import LabelParentsSelector from '@/components/labels/LabelParentsSelector'

/** Unordered equality check for arrays with unique elements (duplicates are prevented by UI). */
function haveSameElements(left: readonly string[], right: readonly string[]): boolean {
  if (left.length !== right.length) return false
  const rightSet = new Set(right)
  return left.every((item) => rightSet.has(item))
}

function haveSameOrder(left: readonly string[], right: readonly string[]): boolean {
  if (left.length !== right.length) return false
  return left.every((item, index) => item === right[index])
}

export default function LabelSettingsPage() {
  const { labelId } = useParams()
  const navigate = useNavigate()
  const { isReady } = useRequireAdmin()

  const { data: allLabels = [], isLoading: allLabelsLoading } = useLabels()

  const [label, setLabel] = useState<LabelResponse | null>(null)
  const [labelLoading, setLabelLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Editable state
  const [names, setNames] = useState<string[]>([])
  const [parents, setParents] = useState<string[]>([])
  const [savedNames, setSavedNames] = useState<string[]>([])
  const [savedParents, setSavedParents] = useState<string[]>([])
  // Async operation state
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const busy = saving || deleting

  const loading = labelLoading || allLabelsLoading

  useEffect(() => {
    if (!isReady) return
    if (labelId === undefined) return
    setLabelLoading(true)
    setError(null)
    void fetchLabel(labelId)
      .then((l) => {
        setLabel(l)
        setNames(l.names)
        setParents(l.parents)
        setSavedNames(l.names)
        setSavedParents(l.parents)
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
        setLabelLoading(false)
      })
  }, [labelId, isReady])

  const excludedIds = useMemo(() => {
    if (labelId === undefined) return new Set<string>()
    const labelsById = new Map(allLabels.map((l) => [l.id, l]))
    const descendants = computeDescendants(labelId, labelsById)
    descendants.add(labelId)
    return descendants
  }, [labelId, allLabels])

  const isDirty = useMemo(() => {
    if (!haveSameOrder(names, savedNames)) return true
    return !haveSameElements(parents, savedParents)
  }, [names, savedNames, parents, savedParents])

  const { markSaved } = useUnsavedChanges(isDirty)

  const availableParents = useMemo(() => allLabels.filter((l) => !excludedIds.has(l.id)), [allLabels, excludedIds])

  const handleNamesChange = useCallback((updated: string[]) => {
    setNames(updated)
    setError(null)
  }, [])

  const handleParentsChange = useCallback((updated: string[]) => {
    setParents(updated)
    setError(null)
  }, [])

  async function handleSave() {
    if (labelId === undefined) return
    setSaving(true)
    setError(null)
    try {
      const updated = await updateLabel(labelId, { names, parents })
      setLabel(updated)
      setNames(updated.names)
      setParents(updated.parents)
      setSavedNames(updated.names)
      setSavedParents(updated.parents)
      markSaved()
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
      markSaved()
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

  if (!isReady) {
    return null
  }

  if (loading) {
    return <LoadingSpinner />
  }

  if (error !== null && label === null) {
    return <ErrorBlock message={error} backTo="/labels" backLabel="Back to labels" />
  }

  return (
    <div className="animate-fade-in">
      <div className="mb-6">
        <BackLink to={`/labels/${labelId}`} label={`Back to #${labelId}`} />
      </div>

      <div className="flex items-center gap-3 mb-8">
        <Settings size={20} className="text-accent" />
        <h1 className="font-display text-3xl text-ink">Label Settings: #{labelId}</h1>
        <div className="ml-auto">
          <button
            onClick={() => void handleSave()}
            disabled={busy || !isDirty}
            className="px-6 py-2.5 text-sm font-medium bg-accent text-white rounded-lg
                     hover:bg-accent-light disabled:opacity-50 transition-colors"
          >
            {saving ? 'Saving...' : 'Save Changes'}
          </button>
        </div>
      </div>

      {error !== null && (
        <AlertBanner variant="error" className="mb-6">{error}</AlertBanner>
      )}

      <LabelNamesEditor
        names={names}
        onNamesChange={handleNamesChange}
        disabled={busy}
      />

      <LabelParentsSelector
        parents={parents}
        onParentsChange={handleParentsChange}
        availableParents={availableParents}
        disabled={busy}
        hint={`Labels that are descendants of #${labelId} are excluded to prevent cycles.`}
      />

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
