import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

interface TimezoneComboboxProps {
  value: string
  onChange: (tz: string) => void
  disabled: boolean
}

function getDisplayLabel(tz: string, detectedTz: string): string {
  if (tz === 'UTC') {
    const suffix = detectedTz === 'UTC' ? ' (detected)' : ''
    return `UTC${suffix}`
  }
  const segments = tz.split('/')
  const city = (segments.at(-1) ?? tz).replace(/_/g, ' ')
  const suffix = tz === detectedTz ? ' (detected)' : ''
  return `${tz} (${city})${suffix}`
}

function buildTimezoneList(detectedTz: string): string[] {
  const allZones: string[] = Intl.supportedValuesOf('timeZone')
  const zoneSet = new Set(allZones)

  // Ensure UTC is in the set
  zoneSet.add('UTC')

  // Remove detected and UTC from the main list; we'll prepend them
  zoneSet.delete(detectedTz)
  zoneSet.delete('UTC')

  const remaining = [...zoneSet].sort()

  const result: string[] = []

  if (detectedTz === 'UTC') {
    // Only one entry for UTC with (detected)
    result.push('UTC')
  } else {
    result.push(detectedTz)
    result.push('UTC')
  }

  result.push(...remaining)
  return result
}

export default function TimezoneCombobox({ value, onChange, disabled }: TimezoneComboboxProps) {
  const detectedTz = useMemo(
    () => new Intl.DateTimeFormat().resolvedOptions().timeZone,
    [],
  )

  const timezones = useMemo(() => buildTimezoneList(detectedTz), [detectedTz])

  const getDisplay = useCallback(
    (tz: string) => getDisplayLabel(tz, detectedTz),
    [detectedTz],
  )

  const [isOpen, setIsOpen] = useState(false)
  // null means "not actively searching" — show display format of current value
  const [searchText, setSearchText] = useState<string | null>(null)
  const [highlightIndex, setHighlightIndex] = useState(-1)
  const containerRef = useRef<HTMLDivElement>(null)
  const listboxRef = useRef<HTMLUListElement>(null)

  // Derive the displayed input value: when not searching, show the display format
  const inputValue = searchText ?? getDisplay(value)

  const filteredTimezones = useMemo(() => {
    if (searchText === null || searchText === '') return timezones
    const query = searchText.toLowerCase()
    return timezones.filter((tz) => {
      const display = getDisplay(tz).toLowerCase()
      return display.includes(query) || tz.toLowerCase().includes(query)
    })
  }, [timezones, searchText, getDisplay])

  function openDropdown() {
    if (disabled) return
    setIsOpen(true)
    setSearchText(null)
    setHighlightIndex(-1)
  }

  const closeDropdown = useCallback(() => {
    setIsOpen(false)
    setSearchText(null)
    setHighlightIndex(-1)
  }, [])

  function selectTimezone(tz: string) {
    onChange(tz)
    closeDropdown()
  }

  function handleInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    setSearchText(e.target.value)
    setHighlightIndex(-1)
    if (!isOpen) {
      openDropdown()
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (!isOpen) {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault()
        openDropdown()
      }
      return
    }

    switch (e.key) {
      case 'ArrowDown': {
        e.preventDefault()
        setHighlightIndex((prev) => {
          const next = prev + 1
          return next >= filteredTimezones.length ? 0 : next
        })
        break
      }
      case 'ArrowUp': {
        e.preventDefault()
        setHighlightIndex((prev) => {
          const next = prev - 1
          return next < 0 ? filteredTimezones.length - 1 : next
        })
        break
      }
      case 'Enter': {
        e.preventDefault()
        const selected = filteredTimezones[highlightIndex]
        if (highlightIndex >= 0 && selected !== undefined) {
          selectTimezone(selected)
        }
        break
      }
      case 'Escape': {
        e.preventDefault()
        closeDropdown()
        break
      }
    }
  }

  // Click outside handler
  useEffect(() => {
    if (!isOpen) return
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        closeDropdown()
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [isOpen, closeDropdown])

  // Scroll highlighted option into view
  useEffect(() => {
    if (highlightIndex >= 0 && listboxRef.current) {
      const optionEl = listboxRef.current.children[highlightIndex] as HTMLElement | undefined
      if (optionEl && typeof optionEl.scrollIntoView === 'function') {
        optionEl.scrollIntoView({ block: 'nearest' })
      }
    }
  }, [highlightIndex])

  const activeDescendantId =
    highlightIndex >= 0 && highlightIndex < filteredTimezones.length
      ? `tz-option-${filteredTimezones[highlightIndex]}`
      : undefined

  return (
    <div ref={containerRef} className="relative">
      <input
        id="site-timezone"
        role="combobox"
        aria-expanded={isOpen}
        aria-controls={isOpen ? 'tz-listbox' : undefined}
        aria-activedescendant={activeDescendantId}
        autoComplete="off"
        type="text"
        value={inputValue}
        onChange={handleInputChange}
        onFocus={openDropdown}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        className="w-full px-3 py-2 bg-paper-warm border border-border rounded-lg
                 text-ink text-sm
                 focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/20
                 disabled:opacity-50"
      />
      {isOpen && (
        <ul
          id="tz-listbox"
          ref={listboxRef}
          role="listbox"
          className="absolute z-10 w-full mt-1 bg-paper border border-border rounded-lg shadow-lg max-h-60 overflow-y-auto"
        >
          {filteredTimezones.map((tz, index) => (
            <li
              key={tz}
              id={`tz-option-${tz}`}
              role="option"
              aria-selected={tz === value}
              className={`px-3 py-2 text-sm text-ink cursor-pointer hover:bg-accent/10${
                index === highlightIndex ? ' bg-accent/10' : ''
              }`}
              onMouseDown={(e) => {
                e.preventDefault()
                selectTimezone(tz)
              }}
            >
              {getDisplay(tz)}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
