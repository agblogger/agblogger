import { useEffect, useRef, useState } from 'react'
import { Share2 } from 'lucide-react'

import ShareDropdownContent from './ShareDropdownContent'
import type { ShareProps } from './shareTypes'

export default function ShareButton({ title, author, url, disabled = false }: ShareProps) {
  const [showDropdown, setShowDropdown] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!showDropdown) return
    function handleClickOutside(e: MouseEvent) {
      if (dropdownRef.current !== null && !dropdownRef.current.contains(e.target as Node)) {
        setShowDropdown(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [showDropdown])

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => setShowDropdown((prev) => !prev)}
        aria-label="Share this post"
        disabled={disabled}
        className="flex items-center gap-1 text-muted transition-colors hover:text-ink disabled:cursor-not-allowed disabled:opacity-50"
        title={disabled ? 'Drafts cannot be shared' : 'Share this post'}
      >
        <Share2 size={14} />
        <span className="text-sm">Share</span>
      </button>

      {showDropdown && (
        <div className="animate-fade-in absolute right-0 top-full z-40 mt-2 min-w-[200px] rounded-xl border border-border bg-paper p-2 shadow-lg">
          <ShareDropdownContent
            title={title}
            author={author}
            url={url}
            onClose={() => setShowDropdown(false)}
          />
        </div>
      )}
    </div>
  )
}
