import { Link } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'

interface BackLinkProps {
  to: string
  label?: string
}

export default function BackLink({ to, label = 'Back' }: BackLinkProps) {
  return (
    <Link
      to={to}
      className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink transition-colors"
    >
      <ArrowLeft size={14} />
      {label}
    </Link>
  )
}
