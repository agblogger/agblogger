import { useState } from 'react'
import { X } from 'lucide-react'

interface LabelNamesEditorProps {
  names: string[]
  onNamesChange: (names: string[]) => void
  disabled: boolean
}

export default function LabelNamesEditor({ names, onNamesChange, disabled }: LabelNamesEditorProps) {
  const [newName, setNewName] = useState('')

  function handleAdd() {
    const trimmed = newName.trim()
    if (!trimmed) return
    if (names.includes(trimmed)) return
    onNamesChange([...names, trimmed])
    setNewName('')
  }

  function handleRemove(index: number) {
    onNamesChange(names.filter((_, currentIndex) => currentIndex !== index))
  }

  return (
    <section className="mb-8 p-5 bg-paper border border-border rounded-lg">
      <h2 className="text-sm font-medium text-ink mb-3">Display Names</h2>
      <div className="flex flex-wrap gap-2 mb-3">
        {names.map((name, index) => (
          <span
            key={`${name}-${index}`}
            className="inline-flex items-center gap-1 px-3 py-1.5 text-sm
                     bg-tag-bg text-tag-text rounded-full"
          >
            {name}
            <button
              onClick={() => handleRemove(index)}
              disabled={disabled}
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
              handleAdd()
            }
          }}
          disabled={disabled}
          placeholder="Add a display name..."
          className="flex-1 px-3 py-2 bg-paper-warm border border-border rounded-lg
                   text-ink text-sm
                   focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/20
                   disabled:opacity-50"
        />
        <button
          onClick={handleAdd}
          disabled={disabled || newName.trim().length === 0}
          className="px-4 py-2 text-sm font-medium border border-border rounded-lg
                   hover:bg-paper-warm disabled:opacity-50 transition-colors"
        >
          Add
        </button>
      </div>
      <p className="text-xs text-muted mt-2">Optional aliases shown alongside the label ID.</p>
    </section>
  )
}
