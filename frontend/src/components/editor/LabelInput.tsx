import { useEffect, useRef, useState } from 'react'
import { X } from 'lucide-react'

import { createLabel } from '@/api/labels'
import { HTTPError } from '@/api/client'
import { filterLabelsBySearch } from '@/components/labels/searchUtils'
import { parseErrorDetail } from '@/api/parseError'
import { useLabels } from '@/hooks/useLabels'

interface LabelInputProps {
  value: string[]
  onChange: (labels: string[]) => void
  disabled?: boolean
}

export default function LabelInput({ value, onChange, disabled }: LabelInputProps) {
  const [query, setQuery] = useState('')
  const { data: allLabels = [], error: labelsError, mutate: mutateLabels } = useLabels()
  const [createLoadError, setCreateLoadError] = useState(false)
  const loadError = !!labelsError || createLoadError
  const [open, setOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)
  const [activeIndex, setActiveIndex] = useState(-1)
  const inputRef = useRef<HTMLInputElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  const filtered = filterLabelsBySearch(allLabels, query).filter((l) => !value.includes(l.id))

  const trimmed = query.trim().toLowerCase().replace(/^#/, '')
  const exactMatch = allLabels.some((l) => l.id === trimmed)
  const showCreate = trimmed.length > 0 && !exactMatch && !value.includes(trimmed)

  // Total options: filtered labels + optional create option
  const totalOptions = filtered.length + (showCreate ? 1 : 0)
  const isDropdownOpen = open && totalOptions > 0

  function addLabel(id: string) {
    if (!value.includes(id)) {
      onChange([...value, id])
    }
    setQuery('')
    setOpen(false)
    setActiveIndex(-1)
    inputRef.current?.focus()
  }

  function removeLabel(id: string) {
    onChange(value.filter((l) => l !== id))
  }

  async function handleCreate() {
    if (!trimmed || creating) return
    setCreating(true)
    try {
      const label = await createLabel({ id: trimmed })
      void mutateLabels([...allLabels, label], false)
      setCreateLoadError(false)
      addLabel(label.id)
    } catch (err) {
      if (err instanceof HTTPError && err.response.status === 409) {
        addLabel(trimmed)
      } else if (err instanceof HTTPError && err.response.status === 422) {
        const message = await parseErrorDetail(err.response, 'Invalid label ID')
        setCreateError(message)
      } else {
        setCreateLoadError(true)
      }
    } finally {
      setCreating(false)
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Backspace' && query === '' && value.length > 0) {
      const lastLabel = value[value.length - 1]
      if (lastLabel !== undefined) {
        removeLabel(lastLabel)
      }
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      if (!open) {
        setOpen(true)
        setActiveIndex(0)
      } else if (totalOptions > 0) {
        setActiveIndex((prev) => (prev + 1) % totalOptions)
      }
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault()
      if (open && totalOptions > 0) {
        setActiveIndex((prev) => (prev <= 0 ? totalOptions - 1 : prev - 1))
      }
    }
    if (e.key === 'Enter') {
      e.preventDefault()
      if (activeIndex >= 0 && activeIndex < filtered.length) {
        const selected = filtered[activeIndex]
        if (selected) {
          addLabel(selected.id)
        }
      } else if (activeIndex === filtered.length && showCreate) {
        void handleCreate()
      } else if (showCreate) {
        void handleCreate()
      } else if (filtered.length > 0) {
        const first = filtered[0]
        if (first) {
          addLabel(first.id)
        }
      }
    }
    if (e.key === 'Escape') {
      setOpen(false)
      setActiveIndex(-1)
    }
  }

  // Reset active index and clear validation errors when query changes
  useEffect(() => {
    setActiveIndex(-1)
    setCreateError(null)
  }, [query])

  return (
    <div ref={containerRef} className="relative">
      <div
        className="flex flex-wrap items-center gap-1.5 px-3 py-2 bg-paper-warm border border-border
                    rounded-lg focus-within:border-accent focus-within:ring-1 focus-within:ring-accent/20
                    min-h-[2.5rem]"
      >
        {value.map((id) => (
          <span
            key={id}
            className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium
                       bg-accent/10 text-accent rounded-full"
          >
            #{id}
            {disabled !== true && (
              <button
                type="button"
                onClick={() => removeLabel(id)}
                aria-label={`Remove label ${id}`}
                className="hover:text-accent-light"
              >
                <X size={12} />
              </button>
            )}
          </span>
        ))}
        <input
          ref={inputRef}
          type="text"
          role="combobox"
          aria-expanded={isDropdownOpen}
          aria-autocomplete="list"
          aria-controls="label-listbox"
          aria-activedescendant={activeIndex >= 0 ? `label-option-${activeIndex}` : undefined}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value)
            setOpen(true)
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          placeholder={value.length === 0 ? (loadError ? 'Failed to load labels' : 'Add labels...') : ''}
          className="flex-1 min-w-[80px] bg-transparent text-sm text-ink outline-none
                     placeholder:text-muted disabled:opacity-50"
        />
      </div>

      {loadError && (
        <p className="mt-1 text-xs text-red-600 dark:text-red-400">
          Failed to load labels. Type to create new ones.
        </p>
      )}

      {createError !== null && (
        <p className="mt-1 text-xs text-red-600 dark:text-red-400">
          {createError}
        </p>
      )}

      {isDropdownOpen && (
        <div
          id="label-listbox"
          role="listbox"
          className="absolute z-10 mt-1 w-full bg-paper border border-border rounded-lg
                      shadow-lg max-h-48 overflow-y-auto"
        >
          {filtered.map((label, index) => {
            const primaryName = label.names[0]
            return (
            <button
              key={label.id}
              id={`label-option-${index}`}
              role="option"
              aria-selected={index === activeIndex}
              type="button"
              onClick={() => addLabel(label.id)}
              className={`w-full text-left px-3 py-2 text-sm transition-colors ${
                index === activeIndex ? 'bg-paper-warm' : 'hover:bg-paper-warm'
              }`}
            >
              <span className="font-medium">#{label.id}</span>
              {primaryName !== undefined && primaryName !== label.id && (
                <span className="ml-2 text-muted">{primaryName}</span>
              )}
            </button>
            )
          })}
          {showCreate && (
            <button
              id={`label-option-${filtered.length}`}
              role="option"
              aria-selected={activeIndex === filtered.length}
              type="button"
              onClick={() => void handleCreate()}
              disabled={creating}
              className={`w-full text-left px-3 py-2 text-sm text-accent transition-colors
                         border-t border-border disabled:opacity-50 ${
                           activeIndex === filtered.length ? 'bg-paper-warm' : 'hover:bg-paper-warm'
                         }`}
            >
              {creating ? 'Creating...' : `Create #${trimmed}`}
            </button>
          )}
        </div>
      )}
    </div>
  )
}
