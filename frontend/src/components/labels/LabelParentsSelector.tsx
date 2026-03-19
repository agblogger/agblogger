import { memo } from 'react'
import type { LabelResponse } from '@/api/client'

interface LabelParentsSelectorProps {
  parents: string[]
  onParentsChange: (parents: string[]) => void
  availableParents: LabelResponse[]
  disabled: boolean
  hint?: string
}

function LabelParentsSelector({
  parents,
  onParentsChange,
  availableParents,
  disabled,
  hint,
}: LabelParentsSelectorProps) {
  function handleToggle(parentId: string) {
    if (parents.includes(parentId)) {
      onParentsChange(parents.filter((p) => p !== parentId))
    } else {
      onParentsChange([...parents, parentId])
    }
  }

  return (
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
                onChange={() => handleToggle(candidate.id)}
                disabled={disabled}
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
      {hint != null && <p className="text-xs text-muted mt-2">{hint}</p>}
    </section>
  )
}

export default memo(LabelParentsSelector)
