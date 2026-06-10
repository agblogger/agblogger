interface ToggleSwitchProps {
  id: string
  label: string
  checked: boolean
  disabled: boolean
  onChange: (value: boolean) => void
}

export default function ToggleSwitch({
  id,
  label,
  checked,
  disabled,
  onChange,
}: ToggleSwitchProps) {
  return (
    <div className="flex items-center gap-2 cursor-pointer select-none">
      <span className="text-sm text-ink" id={`${id}-label`}>{label}</span>
      <button
        id={id}
        role="switch"
        aria-checked={checked}
        aria-labelledby={`${id}-label`}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`relative inline-flex w-10 h-5 rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-accent/40 disabled:opacity-50 disabled:cursor-not-allowed ${
          checked ? 'bg-accent' : 'bg-border'
        }`}
      >
        <span
          className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${
            checked ? 'translate-x-5' : 'translate-x-0'
          }`}
        />
      </button>
    </div>
  )
}
