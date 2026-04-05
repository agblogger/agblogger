import type { DateRange, CustomDateRange } from '@/hooks/useAnalyticsDashboard'

interface DateRangePickerProps {
  value: DateRange
  onChange: (range: DateRange) => void
  disabled: boolean
}

const PRESETS = ['7d', '30d', '90d'] as const

function todayLocalDate(): string {
  const now = new Date()
  const year = String(now.getFullYear())
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function activePreset(value: DateRange): string | null {
  if (typeof value === 'string') return value
  return null
}

function currentCustomRange(value: DateRange): CustomDateRange | null {
  if (typeof value === 'object') return value
  return null
}

export default function DateRangePicker({ value, onChange, disabled }: DateRangePickerProps) {
  const today = todayLocalDate()
  const custom = currentCustomRange(value)
  const preset = activePreset(value)

  const startVal = custom?.start ?? ''
  const endVal = custom?.end ?? ''

  const hasCustom = custom !== null
  const rangeInvalid = hasCustom && startVal !== '' && endVal !== '' && startVal > endVal

  function handlePresetClick(p: (typeof PRESETS)[number]) {
    onChange(p)
  }

  function handleStartChange(e: React.ChangeEvent<HTMLInputElement>) {
    const newStart = e.target.value
    const newEnd = endVal !== '' ? endVal : today
    onChange({ start: newStart, end: newEnd })
  }

  function handleEndChange(e: React.ChangeEvent<HTMLInputElement>) {
    const newStart = startVal !== '' ? startVal : today
    const newEnd = e.target.value
    onChange({ start: newStart, end: newEnd })
  }

  return (
    <div className="flex flex-wrap items-center gap-3">
      {/* Preset buttons */}
      <div className="flex items-center gap-1">
        {PRESETS.map((p) => (
          <button
            key={p}
            onClick={() => { handlePresetClick(p) }}
            disabled={disabled}
            aria-pressed={preset === p}
            className={`px-3 py-1.5 text-sm font-medium rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
              preset === p
                ? 'bg-accent text-white'
                : 'text-muted hover:text-ink border border-border hover:bg-surface'
            }`}
          >
            {p}
          </button>
        ))}
      </div>

      {/* Date inputs */}
      <div className="flex items-center gap-2">
        <input
          type="date"
          aria-label="Start date"
          value={startVal}
          max={today}
          disabled={disabled}
          onChange={handleStartChange}
          className="text-sm border border-border rounded-lg px-2 py-1.5 bg-surface text-ink disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-accent/40"
        />
        <span className="text-muted text-sm">to</span>
        <input
          type="date"
          aria-label="End date"
          value={endVal}
          max={today}
          disabled={disabled}
          onChange={handleEndChange}
          className="text-sm border border-border rounded-lg px-2 py-1.5 bg-surface text-ink disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-accent/40"
        />
      </div>

      {/* Validation error */}
      {rangeInvalid && (
        <p className="w-full text-sm text-red-600 dark:text-red-400">
          Start date must be before end date
        </p>
      )}
    </div>
  )
}
