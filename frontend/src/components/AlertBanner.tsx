interface AlertBannerProps {
  variant: 'error' | 'success' | 'warning'
  children: React.ReactNode
  className?: string
}

const styles = {
  error: 'text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/30 border-red-200 dark:border-red-800/40',
  success: 'text-green-700 dark:text-green-400 bg-green-50 dark:bg-green-950/30 border-green-200 dark:border-green-800/40',
  warning: 'text-amber-800 dark:text-amber-300 bg-amber-50 dark:bg-amber-950/30 border-amber-300 dark:border-amber-700/40',
} as const

export default function AlertBanner({ variant, children, className = '' }: AlertBannerProps) {
  return (
    <div className={`text-sm border rounded-lg px-4 py-3 ${styles[variant]} ${className}`}>
      {children}
    </div>
  )
}
