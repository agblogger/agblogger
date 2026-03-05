import { memo } from 'react'
import { Link } from 'react-router-dom'

interface LabelChipProps {
  labelId: string
  clickable?: boolean
}

function LabelChipInner({ labelId, clickable = true }: LabelChipProps) {
  const className =
    'inline-flex items-center px-2.5 py-1 text-xs font-semibold rounded-lg border border-border/60 ' +
    'bg-tag-bg text-tag-text transition-colors hover:bg-border hover:text-ink'

  if (clickable) {
    return (
      <Link
        to={`/labels/${labelId}`}
        className={className}
        onClick={(e) => e.stopPropagation()}
      >
        #{labelId}
      </Link>
    )
  }

  return <span className={className}>#{labelId}</span>
}

const LabelChip = memo(LabelChipInner)
export default LabelChip
