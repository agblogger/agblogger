import { Link } from 'react-router-dom'

const handleStopPropagation = (e: React.MouseEvent) => e.stopPropagation()

interface ParentLabelLinksProps {
  parents: string[]
  stopPropagation?: boolean
}

export default function ParentLabelLinks({ parents, stopPropagation = false }: ParentLabelLinksProps) {
  return (
    <>
      {parents.map((p, idx) => (
        <span key={p}>
          {idx > 0 && ', '}
          <Link
            to={`/labels/${p}`}
            className="text-muted hover:text-ink underline decoration-border hover:decoration-ink transition-colors"
            onClick={stopPropagation ? handleStopPropagation : undefined}
          >
            #{p}
          </Link>
        </span>
      ))}
    </>
  )
}
