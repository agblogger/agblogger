export default function LoadingSpinner({ size = 'md' }: { size?: 'sm' | 'md' }) {
  const px = size === 'sm' ? 'w-4 h-4' : 'w-6 h-6'
  return (
    <div className="flex items-center justify-center py-24" role="status" aria-label="Loading">
      <div className={`${px} border-2 border-accent/30 border-t-accent rounded-full animate-spin`} />
    </div>
  )
}
