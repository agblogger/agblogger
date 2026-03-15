import { Link } from 'react-router-dom'

interface ErrorBlockProps {
  message: string
  backTo: string
  backLabel: string
}

export default function ErrorBlock({ message, backTo, backLabel }: ErrorBlockProps) {
  return (
    <div className="text-center py-24">
      <p className="text-red-600 dark:text-red-400">{message}</p>
      <Link to={backTo} className="text-accent text-sm hover:underline mt-4 inline-block">
        {backLabel}
      </Link>
    </div>
  )
}
